"""End-to-end local Compose check using PostgreSQL, Kubo, worker, and verifier."""
import os
import time

import httpx

from clintr.compute import MODEL, MLP_MODEL, digest, raw_cid, run


def main():
    token = os.environ["CLINTR_DEMO_TOKEN"]
    base = os.environ.get("CLINTR_API_URL", "http://127.0.0.1:8000")
    with httpx.Client(base_url=base, headers={"X-Demo-Token": token}, timeout=20) as client:
        for model, source in ((MODEL, b"Clintr local Compose integration check"), (MLP_MODEL, b'{"features":[12,-5,3,8,0,1,-2,4]}')):
            run_job(client, model, source)


def run_job(client, model, source):
    response = client.post("/blobs", content=source)
    response.raise_for_status()
    cid = response.json()["cid"]
    assert cid == raw_cid(source)
    response = client.post("/jobs", json={"client": "local-smoke", "model_id": model, "input_cid": cid, "tip": 3, "deadline_seconds": 30})
    response.raise_for_status()
    job_id = response.json()["job_id"]
    for _ in range(40):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(1)
    assert job["status"] == "completed", job
    output = client.get(f"/blobs/{job['output_cid']}").content
    assert output == run(model, source)
    assert job["proof_hash"] == digest(output)
    print({"job_id": job_id, "status": job["status"], "model": model, "output_cid": job["output_cid"]})


if __name__ == "__main__":
    main()
