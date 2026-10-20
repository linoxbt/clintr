"""Exercise one isolated PostgreSQL job under concurrent settlement."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import psycopg

from clintr.compute import MODEL, digest, raw_cid
from clintr.db import Grid


def main():
    base = os.environ["CLINTR_DATABASE_URL"]
    schema = "audit_" + uuid.uuid4().hex[:12]
    with psycopg.connect(base, autocommit=True) as db:
        db.execute(f"CREATE SCHEMA {schema}")
    try:
        scoped = base + ("&" if "?" in base else "?") + "options=" + quote(f"-csearch_path={schema}")
        grid = Grid(scoped)
        grid.register("worker", 50)
        job = grid.create_job("client", MODEL, raw_cid(b"input"), 3, 60)
        grid.assign(job, "worker")
        grid.submit(job, "worker", raw_cid(b"output"), digest(b"output"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: settle(grid, job), range(8)))
        assert results.count("settled") == 1, results
        assert grid.get_job(job)["status"] == "completed"
        with grid.tx() as db:
            count = db.execute("SELECT count(*) AS count FROM ledger WHERE job_id=? AND reason='tip_paid'", (job,)).fetchone()["count"]
        assert count == 1, count
        print("PostgreSQL concurrency check passed: one settlement and one tip payment")
    finally:
        with psycopg.connect(base, autocommit=True) as db:
            db.execute(f"DROP SCHEMA {schema} CASCADE")


def settle(grid, job):
    try:
        grid.settle(job, True)
        return "settled"
    except ValueError:
        return "already settled"


if __name__ == "__main__":
    main()
