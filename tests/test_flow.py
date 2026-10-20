import time

from fastapi.testclient import TestClient

from clintr.compute import MODEL, MLP_MODEL, digest, raw_cid, run
from clintr.db import Grid
from clintr.store import BlobStore, KuboStore
import clintr.api as api


def test_complete_and_reject(tmp_path, monkeypatch):
    monkeypatch.setenv("CLINTR_DB", str(tmp_path / "grid.db"))
    monkeypatch.setenv("CLINTR_BLOBS", str(tmp_path / "blobs"))
    monkeypatch.setenv("CLINTR_DEMO_TOKEN", "test-secret")
    monkeypatch.setattr(api, "grid", Grid(str(tmp_path / "grid.db")))
    monkeypatch.setattr(api, "blobs", BlobStore(str(tmp_path / "blobs")))
    client = TestClient(api.app)
    auth = {"X-Demo-Token": "test-secret"}
    assert client.get("/").status_code == 200
    assert "Clintr" in client.get("/").text
    assert "blind trust." in client.get("/").text
    assert 'data-wallet-button' in client.get("/").text
    assert "projectId" in client.get("/wallet/config").json()
    for page, label in {"overview": "grid overview", "jobs": "compute jobs", "nodes": "edge nodes", "activity": "grid activity", "settings": "settings"}.items():
        response = client.get(f"/app/{page}")
        assert response.status_code == 200
        assert f"<title>{page.title()} | Clintr</title>" in response.text
        assert f"Loading {label}…" in response.text
        assert f'href="/app/{page}"' in response.text
    assert client.get("/app/unknown").status_code == 404
    assert client.get("/assets/logo-dark.svg").status_code == 200
    assert client.post("/auth/check", headers=auth).json()["valid"] is True
    assert client.post("/nodes/register", json={"address": "node-1", "stake": 50}, headers=auth).status_code == 200
    uploaded = client.post("/blobs", content=b"hello", headers=auth).json()
    assert uploaded["cid"] == raw_cid(b"hello")
    job = client.post("/jobs", json={"client": "alice", "model_id": MODEL, "input_cid": uploaded["cid"], "tip": 3}, headers=auth).json()["job_id"]
    assert client.post(f"/jobs/{job}/assign", json={"node": "node-1"}, headers=auth).status_code == 200
    output = run(MODEL, b"hello")
    result_cid = client.post("/blobs", content=output, headers=auth).json()["cid"]
    assert client.post(f"/jobs/{job}/result", json={"node": "node-1", "output_cid": result_cid, "proof_hash": digest(output)}, headers=auth).status_code == 200
    assert client.post(f"/jobs/{job}/verify", headers=auth).json() == {"valid": True, "status": "completed"}
    assert client.post(f"/jobs/{job}/verify", headers=auth).status_code == 409
    assert api.grid.stats()["nodes"][0]["stake"] == 50
    assert len(client.get("/jobs").json()) == 1
    assert any(event["kind"] == "job_completed" for event in client.get("/events").json())

    bad_job = client.post("/jobs", json={"client": "alice", "model_id": MODEL, "input_cid": uploaded["cid"], "tip": 3}, headers=auth).json()["job_id"]
    client.post(f"/jobs/{bad_job}/assign", json={"node": "node-1"}, headers=auth)
    bad_output = b"wrong answer"
    bad_cid = client.post("/blobs", content=bad_output, headers=auth).json()["cid"]
    client.post(f"/jobs/{bad_job}/result", json={"node": "node-1", "output_cid": bad_cid, "proof_hash": digest(bad_output)}, headers=auth)
    assert client.post(f"/jobs/{bad_job}/verify", headers=auth).json()["valid"] is False
    assert api.grid.stats()["nodes"][0]["stake"] == 25
    assert 'clintr_jobs_success_total' in client.get('/metrics').text


def test_deadline_requeue_and_heartbeat_slash(tmp_path):
    grid = Grid(str(tmp_path / "grid.db"))
    now = int(time.time())
    grid.register("node", 50, now)
    job = grid.create_job("alice", MODEL, raw_cid(b"data"), 2, 5, now)
    grid.assign(job, "node", now)
    assert grid.maintenance(now + 6)["requeued_jobs"] == 1
    assert grid.get_job(job)["status"] == "requeued"
    assert grid.get_job(job)["attempts"] == 1
    assert grid.maintenance(now + 37)["requeued_jobs"] == 1
    assert grid.maintenance(now + 91)["pruned_nodes"] == 1
    assert grid.stats()["nodes"][0]["stake"] == 25
    assert grid.get_job(job)["status"] == "cancelled"
    with grid.tx() as db:
        refunds = db.execute("SELECT count(*) AS count FROM ledger WHERE job_id=? AND reason='tip_refunded'", (job,)).fetchone()["count"]
    assert refunds == 1


def test_bad_auth_and_late_result(tmp_path, monkeypatch):
    monkeypatch.setenv("CLINTR_DB", str(tmp_path / "grid.db"))
    monkeypatch.setenv("CLINTR_BLOBS", str(tmp_path / "blobs"))
    monkeypatch.setenv("CLINTR_DEMO_TOKEN", "secret")
    monkeypatch.setattr(api, "grid", Grid(str(tmp_path / "grid.db")))
    monkeypatch.setattr(api, "blobs", BlobStore(str(tmp_path / "blobs")))
    client = TestClient(api.app)
    assert client.post("/nodes/register", json={"address": "n", "stake": 50}).status_code == 401
    now = int(time.time())
    api.grid.register("n", 50, now)
    job = api.grid.create_job("c", MODEL, raw_cid(b"x"), 1, 1, now)
    api.grid.assign(job, "n", now)
    try:
        api.grid.submit(job, "n", raw_cid(b"y"), digest(b"y"), now + 2)
        assert False, "late result accepted"
    except ValueError:
        pass


def test_kubo_raw_block_round_trip(monkeypatch):
    import httpx
    calls = []
    block = b"pinned data"
    cid = raw_cid(block)

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/put"):
            return httpx.Response(200, json={"Key": cid}, request=httpx.Request("POST", url))
        return httpx.Response(200, content=block, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    store = KuboStore("http://ipfs:5001")
    assert store.put(block) == cid
    assert calls[0][1]["params"]["pin"] == "true"
    assert store.get(cid) == block


def test_worker_queue_reads_oldest_jobs_first(tmp_path):
    grid = Grid(str(tmp_path / "grid.db"))
    created = [grid.create_job("alice", MODEL, raw_cid(b"x"), 1, 60, 100 + i) for i in range(105)]
    assert [job["id"] for job in grid.list_jobs("open", 100, oldest_first=True)][0] == created[0]
    assert created[0] not in [job["id"] for job in grid.list_jobs("open", 100)]


def test_unavailable_proof_refunded_after_grace_once(tmp_path):
    grid = Grid(str(tmp_path / "grid.db"))
    now = int(time.time())
    grid.register("node", 50, now)
    job = grid.create_job("client", MODEL, raw_cid(b"input"), 4, 10, now)
    grid.assign(job, "node", now)
    grid.submit(job, "node", raw_cid(b"output"), digest(b"output"), now + 1)
    assert grid.maintenance(now + 3610)["expired_proofs"] == 0
    assert grid.maintenance(now + 3611)["expired_proofs"] == 1
    assert grid.maintenance(now + 3612)["expired_proofs"] == 0
    assert grid.get_job(job)["status"] == "cancelled"
    with grid.tx() as db:
        count = db.execute("SELECT count(*) AS count FROM ledger WHERE job_id=? AND reason='tip_refunded'", (job,)).fetchone()["count"]
    assert count == 1


def test_integer_mlp_reference_vector_and_validation():
    source = b'{"features":[12,-5,3,8,0,1,-2,4]}'
    assert run(MLP_MODEL, source) == b'{"class":0,"scores":[86,-3]}'
    for invalid in (b'{"features":[1,2]}', b'{"features":[1,2,3,4,5,6,7,true]}', b'{"features":[1,2,3,4,5,6,7,128]}'):
        try:
            run(MLP_MODEL, invalid)
            assert False, "invalid model input accepted"
        except ValueError:
            pass
