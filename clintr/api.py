"""Local demonstration API; the contract is the authority for real GEN transfers."""
import os
import time
import httpx
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .compute import MAX_INPUT, MAX_OUTPUT, MODEL, MLP_MODEL, MODELS, digest, run, verify
from .db import Grid
from .store import configured_store

app = FastAPI(title="Clintr", version="0.1.0")
grid = Grid(os.environ.get("CLINTR_DATABASE_URL") or os.environ.get("CLINTR_DB", "/tmp/clintr-demo.sqlite3"))
blobs = configured_store()
jobs_total = Counter("clintr_jobs_total", "Jobs created")
jobs_success = Counter("clintr_jobs_success_total", "Jobs verified successfully")
jobs_failed = Counter("clintr_jobs_failed_total", "Jobs rejected by verifier")
verification_latency = Histogram("clintr_verification_seconds", "Verification duration")


def demo_auth(x_demo_token: str = Header(default="")):
    token = os.environ.get("CLINTR_DEMO_TOKEN")
    if not token or x_demo_token != token:
        raise HTTPException(401, "Set CLINTR_DEMO_TOKEN and send X-Demo-Token")


class NodeRegister(BaseModel):
    address: str = Field(min_length=1, max_length=100)
    stake: int = Field(ge=50)


class JobCreate(BaseModel):
    client: str = Field(min_length=1, max_length=100)
    model_id: str = MODEL
    input_cid: str
    tip: int = Field(ge=1)
    deadline_seconds: int = Field(default=30, ge=1, le=3600)


class Assign(BaseModel):
    node: str


class Result(BaseModel):
    node: str
    output_cid: str
    proof_hash: str


class Cancel(BaseModel):
    client: str


def handle(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, "Unknown job")
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/health")
def health():
    return {"status": "ok", "mode": "local_demo"}


@app.get("/config")
def config():
    return {"name": "Clintr", "mode": "local_demo", "models": [{"id": MODEL, "name": "Byte histogram", "description": "A deterministic 16-bin transform", "max_input_bytes": MAX_INPUT}, {"id": MLP_MODEL, "name": "Edge MLP", "description": "Fixed-weight integer neural inference over eight features", "max_input_bytes": MAX_INPUT}], "min_stake": 50, "heartbeat_seconds": 30}


@app.get("/wallet/config")
def wallet_config():
    return {"projectId": os.environ.get("CLINTR_REOWN_PROJECT_ID", "f0d6f8162be1beccf221b4e2f8bd7026")}


@app.post("/auth/check", dependencies=[Depends(demo_auth)])
def check_access():
    return {"valid": True, "mode": "local_demo"}


@app.post("/blobs", dependencies=[Depends(demo_auth)])
async def upload_blob(request: Request):
    data = await request.body()
    if len(data) > MAX_INPUT:
        raise HTTPException(413, "Blob exceeds 64 KiB")
    try:
        return {"cid": blobs.put(data), "sha256": digest(data)}
    except httpx.HTTPError:
        raise HTTPException(503, "IPFS unavailable")


@app.get("/blobs/{cid}")
def get_blob(cid: str):
    try:
        return Response(blobs.get(cid), media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff", "Content-Disposition": "attachment"})
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "Unknown CID")
    except httpx.HTTPError:
        raise HTTPException(503, "IPFS unavailable")


@app.post("/nodes/register", dependencies=[Depends(demo_auth)])
def register(payload: NodeRegister):
    handle(grid.register, payload.address, payload.stake)
    return {"status": "registered", "address": payload.address, "stake": payload.stake}


@app.post("/nodes/{address}/heartbeat", dependencies=[Depends(demo_auth)])
def heartbeat(address: str):
    handle(grid.heartbeat, address)
    return {"status": "alive"}


@app.get("/nodes")
def list_nodes():
    return grid.stats()["nodes"]


@app.post("/nodes/{address}/withdraw", dependencies=[Depends(demo_auth)])
def withdraw_node(address: str):
    amount = handle(grid.withdraw_node, address)
    return {"status": "withdrawn", "amount": amount}


@app.post("/jobs", dependencies=[Depends(demo_auth)])
def create_job(payload: JobCreate):
    try:
        input_bytes = blobs.get(payload.input_cid)
    except (ValueError, FileNotFoundError):
        raise HTTPException(400, "Input CID is unavailable")
    except httpx.HTTPError:
        raise HTTPException(503, "IPFS unavailable")
    try:
        run(payload.model_id, input_bytes)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    job_id = handle(grid.create_job, payload.client, payload.model_id, payload.input_cid, payload.tip, payload.deadline_seconds)
    jobs_total.inc()
    return {"job_id": job_id, "required_tip": payload.tip, "status": "open"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return handle(grid.get_job, job_id)


@app.get("/jobs")
def list_jobs(status: str | None = None, limit: int = Query(default=50, ge=1, le=100), oldest_first: bool = False):
    return grid.list_jobs(status, limit, oldest_first)


@app.post("/jobs/{job_id}/assign", dependencies=[Depends(demo_auth)])
def assign(job_id: str, payload: Assign):
    handle(grid.assign, job_id, payload.node)
    return {"status": "assigned", "node": payload.node}


@app.post("/jobs/{job_id}/result", dependencies=[Depends(demo_auth)])
def submit_result(job_id: str, payload: Result):
    handle(grid.submit, job_id, payload.node, payload.output_cid, payload.proof_hash)
    return {"status": "pending_verification"}


@app.post("/jobs/{job_id}/verify", dependencies=[Depends(demo_auth)])
def verify_job(job_id: str):
    job = handle(grid.get_job, job_id)
    if job["status"] != "pending_verification":
        raise HTTPException(409, "Job is not awaiting verification")
    start = time.monotonic()
    try:
        input_data = blobs.get(job["input_cid"])
        output_data = blobs.get(job["output_cid"])
    except (FileNotFoundError, ValueError, httpx.HTTPError):
        raise HTTPException(503, "Content unavailable; verification can be retried")
    valid = verify(job["model_id"], input_data, output_data, job["output_cid"], job["proof_hash"])
    handle(grid.settle, job_id, valid)
    verification_latency.observe(time.monotonic() - start)
    (jobs_success if valid else jobs_failed).inc()
    return {"valid": valid, "status": "completed" if valid else "failed"}


@app.post("/jobs/{job_id}/cancel", dependencies=[Depends(demo_auth)])
def cancel_job(job_id: str, payload: Cancel):
    handle(grid.cancel_job, job_id, payload.client)
    return {"status": "cancelled"}


@app.post("/maintenance", dependencies=[Depends(demo_auth)])
def maintenance():
    return grid.maintenance()


@app.get("/stats")
def stats():
    return grid.stats()


@app.get("/events")
def list_events(limit: int = Query(default=40, ge=1, le=100)):
    return grid.list_events(limit)


@app.get("/metrics")
def metrics():
    info = grid.stats()
    lines = [generate_latest().decode(), "# HELP clintr_node_up Node heartbeat status\n# TYPE clintr_node_up gauge\n", "# HELP clintr_node_stake Simulated locked GEN units\n# TYPE clintr_node_stake gauge\n"]
    for node in info["nodes"]:
        # Node addresses are escaped because Prometheus label values are untrusted input.
        label = node["address"].replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        up = int(bool(node["active"]) and node["heartbeat"] >= int(time.time()) - 90)
        lines.append(f'clintr_node_up{{address="{label}"}} {up}\nclintr_node_stake{{address="{label}"}} {node["stake"]}\n')
    for status, count in info["jobs"].items():
        lines.append(f'clintr_jobs_status{{status="{status}"}} {count}\n')
    return Response("".join(lines), media_type=CONTENT_TYPE_LATEST)


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    pages = {"overview": "Overview", "jobs": "Jobs", "nodes": "Nodes", "activity": "Activity", "settings": "Settings"}

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        return templates.TemplateResponse(request, "landing.html", {"hosted": False})

    @app.get("/app/{page}", include_in_schema=False)
    def app_page(request: Request, page: str):
        if page not in pages:
            raise HTTPException(404, "Page not found")
        return templates.TemplateResponse(request, f"{page}.html", {"page": page, "page_title": pages[page]})
