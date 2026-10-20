"""Transactional demo ledger. Values are simulated GEN units, never on-chain funds."""
import sqlite3
import time
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

MIN_STAKE = 50
HEARTBEAT_SECONDS = 30


class _PostgresConnection:
    """Small DB-API adapter so the same transactional grid runs on PostgreSQL."""

    def __init__(self, url: str):
        self.connection = psycopg.connect(url, row_factory=dict_row)

    def execute(self, sql: str, params=()):
        return self.connection.execute(sql.replace("?", "%s"), params)

    def executescript(self, script: str):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class Grid:
    def __init__(self, path: str):
        self.path = path
        self.postgres = path.startswith("postgresql://") or path.startswith("postgres://")
        with self.tx() as db:
            ledger_id = "BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY"
            event_id = ledger_id
            db.executescript(f"""
                CREATE TABLE IF NOT EXISTS nodes(address TEXT PRIMARY KEY, stake INTEGER NOT NULL, heartbeat INTEGER NOT NULL, active INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, client TEXT NOT NULL, model_id TEXT NOT NULL, input_cid TEXT NOT NULL, tip INTEGER NOT NULL, deadline INTEGER NOT NULL, assigned_node TEXT, status TEXT NOT NULL, output_cid TEXT, proof_hash TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS ledger(id {ledger_id}, address TEXT NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL, job_id TEXT);
                CREATE TABLE IF NOT EXISTS events(id {event_id}, kind TEXT NOT NULL, job_id TEXT, address TEXT, detail TEXT NOT NULL, created_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_status_deadline ON jobs(status,deadline);
                CREATE INDEX IF NOT EXISTS events_created ON events(created_at DESC);
            """)
            if not self.postgres:
                columns = [row["name"] for row in db.execute("PRAGMA table_info(jobs)")]
                if "created_at" not in columns:
                    db.execute("ALTER TABLE jobs ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")

    def _event(self, db, kind: str, job_id: str | None = None, address: str | None = None, detail: str = ""):
        db.execute("INSERT INTO events(kind,job_id,address,detail,created_at) VALUES (?,?,?,?,?)", (kind, job_id, address, detail, int(time.time())))

    @contextmanager
    def tx(self):
        if self.postgres:
            db = _PostgresConnection(self.path)
        else:
            db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            db.row_factory = sqlite3.Row
        try:
            if not self.postgres:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, address: str, stake: int, now: int | None = None):
        if not address or stake < MIN_STAKE:
            raise ValueError("Address and at least 50 simulated GEN required")
        with self.tx() as db:
            prior = db.execute("SELECT stake,active FROM nodes WHERE address=?", (address,)).fetchone()
            if prior and (prior["stake"] or prior["active"]):
                raise ValueError("Node already registered; withdraw remaining stake first")
            if prior:
                db.execute("UPDATE nodes SET stake=?,heartbeat=?,active=1 WHERE address=?", (stake, now or int(time.time()), address))
            else:
                db.execute("INSERT INTO nodes VALUES (?,?,?,1)", (address, stake, now or int(time.time())))
            db.execute("INSERT INTO ledger(address,delta,reason) VALUES (?,?,?)", (address, -stake, "stake_locked"))
            self._event(db, "node_registered", address=address, detail=f"{stake} GEN staked")

    def heartbeat(self, address: str, now: int | None = None):
        with self.tx() as db:
            result = db.execute("UPDATE nodes SET heartbeat=? WHERE address=? AND active=1", (now or int(time.time()), address))
            if result.rowcount != 1:
                raise ValueError("Unknown or inactive node")

    def create_job(self, client: str, model_id: str, input_cid: str, tip: int, deadline_seconds: int, now: int | None = None) -> str:
        from .compute import MODEL, CID_PATTERN
        if not client or model_id != MODEL or not CID_PATTERN.fullmatch(input_cid) or tip < 1 or not 1 <= deadline_seconds <= 3600:
            raise ValueError("Invalid job parameters")
        job_id = str(uuid.uuid4())
        with self.tx() as db:
            db.execute("INSERT INTO jobs(id,client,model_id,input_cid,tip,deadline,status,created_at) VALUES (?,?,?,?,?,?,?,?)", (job_id, client, model_id, input_cid, tip, (now or int(time.time())) + deadline_seconds, "open", now or int(time.time())))
            db.execute("INSERT INTO ledger(address,delta,reason,job_id) VALUES (?,?,?,?)", (client, -tip, "tip_escrowed", job_id))
            self._event(db, "job_created", job_id, client, f"{model_id} · {tip} GEN tip")
        return job_id

    def list_jobs(self, status: str | None = None, limit: int = 50) -> list[dict]:
        limit = max(1, min(limit, 100))
        with self.tx() as db:
            if status:
                rows = db.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC,id DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC,id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, limit: int = 40) -> list[dict]:
        with self.tx() as db:
            rows = db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 100)),)).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict:
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def assign(self, job_id: str, node: str, now: int | None = None):
        now = now or int(time.time())
        with self.tx() as db:
            active = db.execute("SELECT 1 FROM nodes WHERE address=? AND active=1 AND heartbeat>=?", (node, now - 3 * HEARTBEAT_SECONDS)).fetchone()
            if not active:
                raise ValueError("Node unavailable")
            result = db.execute("UPDATE jobs SET assigned_node=?,status='assigned' WHERE id=? AND status IN ('open','requeued') AND deadline>?", (node, job_id, now))
            if result.rowcount != 1:
                raise ValueError("Job unavailable or expired")
            self._event(db, "job_assigned", job_id, node, "Node accepted job")

    def submit(self, job_id: str, node: str, output_cid: str, proof_hash: str, now: int | None = None):
        from .compute import CID_PATTERN
        import re
        if not CID_PATTERN.fullmatch(output_cid) or not re.fullmatch(r"[0-9a-f]{64}", proof_hash):
            raise ValueError("Invalid result")
        with self.tx() as db:
            result = db.execute("UPDATE jobs SET output_cid=?,proof_hash=?,status='pending_verification' WHERE id=? AND assigned_node=? AND status='assigned' AND deadline>=?", (output_cid, proof_hash, job_id, node, now or int(time.time())))
            if result.rowcount != 1:
                raise ValueError("Wrong node, state, or expired deadline")
            self._event(db, "result_submitted", job_id, node, "Proof queued for verification")

    def settle(self, job_id: str, valid: bool):
        with self.tx() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=? AND status='pending_verification'", (job_id,)).fetchone()
            if job is None:
                raise ValueError("Job is not awaiting verification")
            node = db.execute("SELECT * FROM nodes WHERE address=?", (job["assigned_node"],)).fetchone()
            if valid:
                db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))
                db.execute("INSERT INTO ledger(address,delta,reason,job_id) VALUES (?,?,?,?)", (node["address"], job["tip"], "tip_paid", job_id))
                self._event(db, "job_completed", job_id, node["address"], f"{job['tip']} GEN tip paid")
            else:
                slash = node["stake"] // 2
                db.execute("UPDATE nodes SET stake=stake-?,active=CASE WHEN stake-? < ? THEN 0 ELSE active END WHERE address=?", (slash, slash, MIN_STAKE, node["address"]))
                db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))
                db.execute("INSERT INTO ledger(address,delta,reason,job_id) VALUES (?,?,?,?)", (node["address"], -slash, "stake_slashed", job_id))
                db.execute("INSERT INTO ledger(address,delta,reason,job_id) VALUES (?,?,?,?)", (job["client"], job["tip"], "tip_refunded", job_id))
                self._event(db, "job_failed", job_id, node["address"], f"Invalid proof · {slash} GEN slashed")

    def maintenance(self, now: int | None = None) -> dict:
        now = now or int(time.time())
        with self.tx() as db:
            stale = db.execute("SELECT address,stake FROM nodes WHERE active=1 AND heartbeat<?", (now - 3 * HEARTBEAT_SECONDS,)).fetchall()
            for node in stale:
                slash = node["stake"] // 2
                db.execute("UPDATE nodes SET active=0,stake=stake-? WHERE address=?", (slash, node["address"]))
                db.execute("INSERT INTO ledger(address,delta,reason) VALUES (?,?,?)", (node["address"], -slash, "heartbeat_slash"))
                self._event(db, "node_pruned", address=node["address"], detail=f"Missed heartbeats · {slash} GEN slashed")
            expired = db.execute("SELECT id FROM jobs WHERE status IN ('open','assigned') AND deadline<?", (now,)).fetchall()
            for job in expired:
                db.execute("UPDATE jobs SET status='requeued',assigned_node=NULL,attempts=attempts+1,deadline=? WHERE id=?", (now + 30, job["id"]))
                self._event(db, "job_requeued", job["id"], detail="Deadline elapsed")
            return {"pruned_nodes": len(stale), "requeued_jobs": len(expired)}

    def cancel_job(self, job_id: str, client: str):
        with self.tx() as db:
            job = db.execute("SELECT * FROM jobs WHERE id=? AND client=? AND status='requeued'", (job_id, client)).fetchone()
            if job is None:
                raise ValueError("Only the client can cancel a requeued job")
            db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
            db.execute("INSERT INTO ledger(address,delta,reason,job_id) VALUES (?,?,?,?)", (client, job["tip"], "tip_refunded", job_id))
            self._event(db, "job_cancelled", job_id, client, "Tip refunded")

    def withdraw_node(self, address: str) -> int:
        with self.tx() as db:
            node = db.execute("SELECT * FROM nodes WHERE address=?", (address,)).fetchone()
            if node is None or node["stake"] <= 0:
                raise ValueError("Node has no stake to withdraw")
            assigned = db.execute("SELECT 1 FROM jobs WHERE assigned_node=? AND status IN ('assigned','pending_verification') LIMIT 1", (address,)).fetchone()
            if assigned:
                raise ValueError("Node has an unsettled job")
            db.execute("UPDATE nodes SET active=0,stake=0 WHERE address=?", (address,))
            db.execute("INSERT INTO ledger(address,delta,reason) VALUES (?,?,?)", (address, node["stake"], "stake_withdrawn"))
            self._event(db, "node_withdrew", address=address, detail=f"{node['stake']} GEN withdrawn")
            return node["stake"]

    def stats(self):
        with self.tx() as db:
            jobs = {r["status"]: r["count"] for r in db.execute("SELECT status,count(*) AS count FROM jobs GROUP BY status")}
            nodes = [dict(r) for r in db.execute("SELECT address,stake,heartbeat,active FROM nodes")]
        return {"jobs": jobs, "nodes": nodes}
