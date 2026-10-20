import os
import time
import httpx

from .compute import verify
from .db import Grid
from .store import BlobStore, KuboStore


def main():
    grid = Grid(os.environ.get("CLINTR_DATABASE_URL") or os.environ.get("CLINTR_DB", "/tmp/clintr-demo.sqlite3"))
    blobs = KuboStore(os.environ["CLINTR_IPFS_API"]) if os.environ.get("CLINTR_IPFS_API") else BlobStore(os.environ.get("CLINTR_BLOBS", "/tmp/clintr-blobs"))
    while True:
        result = grid.maintenance()
        for job in grid.list_jobs("pending_verification", 100, oldest_first=True):
            try:
                source = blobs.get(job["input_cid"])
                output = blobs.get(job["output_cid"])
                valid = verify(job["model_id"], source, output, job["output_cid"], job["proof_hash"])
                grid.settle(job["id"], valid)
                result["retried_proofs"] = result.get("retried_proofs", 0) + 1
            except (FileNotFoundError, ValueError, httpx.HTTPError):
                continue
        print(result, flush=True)
        time.sleep(10)


if __name__ == "__main__":
    main()
