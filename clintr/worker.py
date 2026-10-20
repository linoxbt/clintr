"""Poll an assigned job, run deterministic compute, and submit its proof."""
import argparse
import time
import httpx

from .compute import digest, run


def process(base_url: str, token: str, node: str, job_id: str) -> dict:
    headers = {"X-Demo-Token": token}
    with httpx.Client(base_url=base_url, headers=headers, timeout=20) as client:
        job_response = client.get(f"/jobs/{job_id}")
        job_response.raise_for_status()
        job = job_response.json()
        if job["status"] == "open" or job["status"] == "requeued":
            response = client.post(f"/jobs/{job_id}/assign", json={"node": node})
            response.raise_for_status()
        elif job["status"] != "assigned" or job["assigned_node"] != node:
            raise ValueError("Job is not assigned to this node")
        input_response = client.get(f"/blobs/{job['input_cid']}")
        input_response.raise_for_status()
        output = run(job["model_id"], input_response.content)
        uploaded = client.post("/blobs", content=output, headers={"Content-Type": "application/octet-stream"})
        uploaded.raise_for_status()
        cid = uploaded.json()["cid"]
        submitted = client.post(f"/jobs/{job_id}/result", json={"node": node, "output_cid": cid, "proof_hash": digest(output)})
        submitted.raise_for_status()
        verified = client.post(f"/jobs/{job_id}/verify")
        verified.raise_for_status()
        return verified.json()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--node", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    print(process(args.url, args.token, args.node, args.job_id))


if __name__ == "__main__":
    main()
