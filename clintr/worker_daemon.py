"""Demo edge node: heartbeat and process available jobs until stopped."""
import logging
import os
import time

import httpx
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .worker import process

worker_up = Gauge("clintr_worker_node_up", "Worker can reach the API and send heartbeats", ["node"])
jobs_processed = Counter("clintr_worker_jobs_processed_total", "Jobs processed by this worker", ["node", "result"])
job_duration = Histogram("clintr_worker_job_seconds", "End-to-end worker job duration", ["node"])


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = os.environ.get("CLINTR_API_URL", "http://localhost:8000")
    token = os.environ["CLINTR_DEMO_TOKEN"]
    node = os.environ.get("CLINTR_WORKER_NODE", "clintr-demo-node")
    stake = int(os.environ.get("CLINTR_WORKER_STAKE", "50"))
    metrics_port = int(os.environ.get("CLINTR_WORKER_METRICS_PORT", "9101"))
    start_http_server(metrics_port)
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
                    withdrawal = client.post(f"/nodes/{node}/withdraw")
                    if withdrawal.status_code == 400:
                        logging.warning("Node %s cannot withdraw while a job is unsettled", node)
                        time.sleep(15)
                        continue
                    withdrawal.raise_for_status()
                    response = client.post("/nodes/register", json={"address": node, "stake": stake})
                    response.raise_for_status()
                    logging.info("Re-registered pruned demo node %s", node)
                if time.monotonic() - last_heartbeat >= 15:
                    response = client.post(f"/nodes/{node}/heartbeat")
                    response.raise_for_status()
                    last_heartbeat = time.monotonic()
                    worker_up.labels(node).set(1)
                for status in ("open", "requeued"):
                    response = client.get("/jobs", params={"status": status, "limit": 100, "oldest_first": "true"})
                    response.raise_for_status()
                    for job in response.json():
                        try:
                            with job_duration.labels(node).time():
                                verdict = process(url, token, node, job["id"])
                            jobs_processed.labels(node, "valid" if verdict.get("valid") else "invalid").inc()
                            logging.info("Job %s: %s", job["id"], verdict)
                        except (httpx.HTTPError, ValueError) as exc:
                            logging.warning("Job %s was unavailable: %s", job["id"], exc)
        except (httpx.HTTPError, OSError) as exc:
            worker_up.labels(node).set(0)
            logging.warning("API unavailable: %s", exc)
        time.sleep(2)


if __name__ == "__main__":
    main()
