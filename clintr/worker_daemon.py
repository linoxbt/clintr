"""Demo edge node: heartbeat and process available jobs until stopped."""
import logging
import os
import time

import httpx

from .worker import process


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.environ.get("CLINTR_API_URL", "http://localhost:8000")
    token = os.environ["CLINTR_DEMO_TOKEN"]
    node = os.environ.get("CLINTR_WORKER_NODE", "clintr-demo-node")
    stake = int(os.environ.get("CLINTR_WORKER_STAKE", "50"))
    headers = {"X-Demo-Token": token}
    last_heartbeat = 0.0
    while True:
        try:
            with httpx.Client(base_url=url, headers=headers, timeout=20) as client:
                nodes = client.get("/nodes")
                nodes.raise_for_status()
                existing = next((entry for entry in nodes.json() if entry["address"] == node), None)
                if existing is None or (existing["stake"] == 0 and not existing["active"]):
                    response = client.post("/nodes/register", json={"address": node, "stake": stake})
                    response.raise_for_status()
                    logging.info("Registered edge node %s", node)
                elif not existing["active"]:
                    logging.error("Node %s is inactive with remaining stake; manual withdrawal is required", node)
                    time.sleep(15)
                    continue
                if time.monotonic() - last_heartbeat >= 15:
                    response = client.post(f"/nodes/{node}/heartbeat")
                    response.raise_for_status()
                    last_heartbeat = time.monotonic()
                for status in ("open", "requeued"):
                    response = client.get("/jobs", params={"status": status, "limit": 25})
                    response.raise_for_status()
                    for job in response.json():
                        try:
                            verdict = process(url, token, node, job["id"])
                            logging.info("Job %s: %s", job["id"], verdict)
                        except (httpx.HTTPError, ValueError) as exc:
                            logging.warning("Job %s was unavailable: %s", job["id"], exc)
        except (httpx.HTTPError, OSError) as exc:
            logging.warning("API unavailable: %s", exc)
        time.sleep(2)


if __name__ == "__main__":
    main()
