"""Single-node SQLite reference adapter for E-002 storage conformance.

A semantic reference implementation only; it is not a selected product database.
All four admission records share one FULL-synchronous WAL transaction.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class IdempotencyConflict(RuntimeError):
    pass


class SimulatedResponseLoss(RuntimeError):
    """The transaction committed, but the caller did not receive its response."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


CANONICALIZATION_VERSION = "json-sort-keys-compact-utf8-v1"


def _hash(value: Any) -> str:
    canonical = _json(value).encode("utf-8")
    return hashlib.sha256(CANONICALIZATION_VERSION.encode("ascii") + b"\\0" + canonical).hexdigest()


class SQLiteReferenceAdapter:
    """Reference implementation of the E-002 atomic durable admission contract."""

    def __init__(self, database: str | Path, *, _fault_hook=None):
        if str(database) == ":memory:":
            raise ValueError("file_backed_database_required")
        self.database = str(Path(database).expanduser().resolve())
        self._fault_hook = _fault_hook
        self._initialize()

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _initialize(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('queued','completed','failed')),
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    tenant_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    outcome_json TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, operation_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL, job_id TEXT NOT NULL UNIQUE REFERENCES jobs(job_id),
                    payload_json TEXT NOT NULL, created_at INTEGER NOT NULL,
                    lease_owner TEXT, lease_token INTEGER NOT NULL DEFAULT 0,
                    lease_until INTEGER, delivered_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL,
                    tenant_id TEXT, operation_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','deny')),
                    reason_code TEXT NOT NULL, outcome_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS audit_no_update
                BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit_append_only'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete
                BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit_append_only'); END;
            """)
            db.commit()
        finally:
            db.close()

    def _fault(self, stage: str):
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def append_audit(self, event: dict) -> int:
        if not isinstance(event, dict):
            raise ValueError("audit_event_must_be_object")
        event_id = _text(event.get("event_id"), "event_id")
        request_id = _text(event.get("request_id"), "request_id")
        operation_id = _text(event.get("operation_id"), "operation_id")
        decision = event.get("decision")
        if decision not in {"allow", "deny"}:
            raise ValueError("invalid_audit_decision")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """INSERT INTO audit(event_id,request_id,tenant_id,operation_id,
                   decision,reason_code,outcome_json,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (event_id, request_id, event.get("tenant_id"), operation_id,
                 decision, _text(event.get("reason_code"), "reason_code"),
                 _json(event.get("outcome", {})), int(event.get("created_at", time.time()))),
            )
            db.commit()
            return int(cursor.lastrowid)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def admit_job(self, *, tenant_id: str, operation_id: str, idempotency_key: str,
                  payload: dict, outbox_payload: dict, audit_event: dict) -> tuple[str, dict]:
        tenant_id = _text(tenant_id, "tenant_id")
        operation_id = _text(operation_id, "operation_id")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        if not isinstance(payload, dict) or not isinstance(outbox_payload, dict):
            raise ValueError("payloads_must_be_objects")
        if not isinstance(audit_event, dict):
            raise ValueError("audit_event_must_be_object")
        request_hash = _hash({"operation_id": operation_id, "payload": payload})
        payload_json, outbox_json = _json(payload), _json(outbox_payload)
        now = audit_event.get("created_at", int(time.time()))
        if type(now) is not int or now < 0:
            raise ValueError("invalid_created_at")
        request_id = _text(audit_event.get("request_id"), "request_id")
        if _text(audit_event.get("operation_id"), "audit_operation_id") != operation_id:
            raise ValueError("audit_operation_mismatch")

        db = self._connect()
        committed = False
        try:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                """SELECT request_hash,outcome_json FROM idempotency_records
                   WHERE tenant_id=? AND operation_id=? AND idempotency_key=?""",
                (tenant_id, operation_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["request_hash"] != request_hash:
                    status, decision, reason = "conflict", "deny", "IDEMPOTENCY_PAYLOAD_CONFLICT"
                    outcome = {"code": reason}
                else:
                    status, decision, reason = "replayed", "allow", "IDEMPOTENCY_REPLAY"
                    outcome = json.loads(previous["outcome_json"])
                db.execute(
                    """INSERT INTO audit(event_id,request_id,tenant_id,operation_id,
                       decision,reason_code,outcome_json,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), request_id, tenant_id, operation_id,
                     decision, reason, _json(outcome), now),
                )
                db.commit()
                committed = True
                return status, outcome

            job_id, event_id = str(uuid.uuid4()), str(uuid.uuid4())
            outcome = {"job_id": job_id, "state": "queued"}
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?, 'queued', ?)",
                (job_id, tenant_id, operation_id, payload_json, now),
            )
            self._fault("after_job")
            db.execute(
                """INSERT INTO outbox(event_id,tenant_id,operation_id,job_id,payload_json,created_at)
                   VALUES(?,?,?,?,?,?)""",
                (event_id, tenant_id, operation_id, job_id, outbox_json, now),
            )
            self._fault("after_outbox")
            db.execute(
                """INSERT INTO idempotency_records(tenant_id,operation_id,idempotency_key,
                   request_hash,job_id,outcome_json) VALUES(?,?,?,?,?,?)""",
                (tenant_id, operation_id, idempotency_key, request_hash, job_id, _json(outcome)),
            )
            self._fault("after_idempotency")
            db.execute(
                """INSERT INTO audit(event_id,request_id,tenant_id,operation_id,
                   decision,reason_code,outcome_json,created_at)
                   VALUES(?,?,?,?, 'allow','JOB_ADMITTED',?,?)""",
                (str(uuid.uuid4()), request_id, tenant_id, operation_id, _json(outcome), now),
            )
            self._fault("after_audit")
            db.commit()
            committed = True
            self._fault("after_commit")
            return "created", outcome
        except Exception:
            if not committed:
                db.rollback()
            raise
        finally:
            db.close()

    def lookup_idempotency(self, tenant_id: str, operation_id: str, key: str):
        db = self._connect()
        try:
            row = db.execute(
                """SELECT request_hash,outcome_json FROM idempotency_records
                   WHERE tenant_id=? AND operation_id=? AND idempotency_key=?""",
                (tenant_id, operation_id, key),
            ).fetchone()
            return None if row is None else {
                "request_hash": row["request_hash"],
                "outcome": json.loads(row["outcome_json"]),
            }
        finally:
            db.close()

    def read_job(self, job_id: str):
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def read_outbox_for_job(self, job_id: str):
        db = self._connect()
        try:
            row = db.execute("SELECT * FROM outbox WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row else None
        finally:
            db.close()

    def claim_outbox(self, *, consumer: str, limit: int, lease_seconds: int, now: int):
        consumer = _text(consumer, "consumer")
        if type(limit) is not int or limit < 1:
            raise ValueError("invalid_outbox_limit")
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("invalid_outbox_lease")
        if type(now) is not int or now < 0:
            raise ValueError("invalid_outbox_clock")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT event_id FROM outbox
                   WHERE delivered_at IS NULL AND (lease_until IS NULL OR lease_until <= ?)
                   ORDER BY created_at, event_id LIMIT ?""",
                (now, limit),
            ).fetchall()
            claimed = []
            for row in rows:
                db.execute(
                    """UPDATE outbox SET lease_owner=?, lease_token=lease_token+1, lease_until=?
                       WHERE event_id=? AND delivered_at IS NULL""",
                    (consumer, now + lease_seconds, row["event_id"]),
                )
                claimed.append(db.execute(
                    "SELECT * FROM outbox WHERE event_id=?", (row["event_id"],)
                ).fetchone())
            db.commit()
            return [dict(row) for row in claimed]
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def ack_outbox(self, *, event_id: str, consumer: str, lease_token: int, now: int) -> bool:
        event_id = _text(event_id, "event_id")
        consumer = _text(consumer, "consumer")
        if type(lease_token) is not int or lease_token < 1:
            raise ValueError("invalid_outbox_lease_token")
        if type(now) is not int or now < 0:
            raise ValueError("invalid_outbox_clock")
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """UPDATE outbox SET delivered_at=?, lease_owner=NULL, lease_until=NULL
                   WHERE event_id=? AND lease_owner=? AND lease_token=?
                     AND lease_until>? AND delivered_at IS NULL""",
                (now, event_id, consumer, lease_token, now),
            )
            db.commit()
            return cursor.rowcount == 1
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def recover(self) -> dict[str, int]:
        db = self._connect()
        try:
            return {table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in ("jobs", "outbox", "idempotency_records", "audit")}
        finally:
            db.close()

    def metadata(self) -> dict[str, Any]:
        """Return the engine and effective connection durability settings."""
        db = self._connect()
        try:
            return {
                "engine": "sqlite",
                "engine_version": sqlite3.sqlite_version,
                "journal_mode": db.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": int(db.execute("PRAGMA synchronous").fetchone()[0]),
                "foreign_keys": int(db.execute("PRAGMA foreign_keys").fetchone()[0]),
                "busy_timeout_ms": int(db.execute("PRAGMA busy_timeout").fetchone()[0]),
                "canonicalization_version": CANONICALIZATION_VERSION,
                "durability_profile": "WAL + synchronous=FULL",
            }
        finally:
            db.close()
