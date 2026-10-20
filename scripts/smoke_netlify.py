"""Submit one byte histogram job to the hosted Clintr demo."""
import json
import os
from pathlib import Path

import httpx

from clintr.compute import MODEL, digest, raw_cid, run


def main():
    token = os.environ.get("CLINTR_DEMO_TOKEN")
    if not token:
        token = dict(line.split("=", 1) for line in Path(".env").read_text().splitlines())["CLINTR_DEMO_TOKEN"]
    base = os.environ.get("CLINTR_SITE_URL", "https://clintr-grid.netlify.app")
    source = b"Clintr Netlify smoke test"
    with httpx.Client(base_url=base, headers={"X-Demo-Token": token}, timeout=30, follow_redirects=True) as client:
        cid = client.post("/blobs", content=source).raise_for_status().json()["cid"]
        assert cid == raw_cid(source)
        job_id = client.post("/jobs", json={
            "client": "deployment-smoke", "model_id": MODEL, "input_cid": cid,
            "tip": 3, "deadline_seconds": 30,
        }).raise_for_status().json()["job_id"]
        job = client.get(f"/jobs/{job_id}").raise_for_status().json()
        output = client.get(f"/blobs/{job['output_cid']}").raise_for_status().content
        verdict = client.post(f"/jobs/{job_id}/verify").raise_for_status().json()
        assert output == run(MODEL, source)
        assert job["proof_hash"] == digest(output)
        assert job["status"] == "completed" and verdict["valid"] is True
        print(json.dumps({"job_id": job_id, "status": job["status"], "output_cid": job["output_cid"], "verified": verdict["valid"]}))


if __name__ == "__main__":
    main()
