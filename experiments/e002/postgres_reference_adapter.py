"""PostgreSQL reference adapter for the E-002 durable storage contract.

This is a second conformance arm, not a product database selection.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row

CANONICALIZATION_VERSION = "json-sort-keys-compact-utf8-v1"


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    canonical = _json(value).encode("utf-8")
    return hashlib.sha256(CANONICALIZATION_VERSION.encode("ascii") + b"\\0" + canonical).hexdigest()


class PostgresReferenceAdapter:
    def __init__(self, dsn: str | None = None, *, _fault_hook=None):
        self.dsn = dsn or os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN")
        if not self.dsn:
            raise ValueError("postgres_dsn_required")
        self._fault_hook = _fault_hook
        self._initialize()

    def _connect(self):
        connection = psycopg.connect(self.dsn, row_factory=dict_row)
        connection.execute("SET synchronous_commit TO on")
        connection.execute("SET statement_timeout TO '10s'")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS e002_jobs (
                    job_id UUID PRIMARY KEY, tenant_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('queued','completed','failed')),
                    created_at BIGINT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS e002_idempotency_records (
                    tenant_id TEXT NOT NULL, operation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
                    job_id UUID NOT NULL REFERENCES e002_jobs(job_id),
                    outcome_json TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, operation_id, idempotency_key)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS e002_outbox (
                    event_id UUID PRIMARY KEY, tenant_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL, job_id UUID NOT NULL UNIQUE REFERENCES e002_jobs(job_id),
                    payload_json TEXT NOT NULL, created_at BIGINT NOT NULL,
                    lease_owner TEXT, lease_token BIGINT NOT NULL DEFAULT 0,
                    lease_until BIGINT, delivered_at BIGINT
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS e002_audit (
                    sequence BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL UNIQUE,
                    request_id TEXT NOT NULL, tenant_id TEXT, operation_id TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow','deny')),
                    reason_code TEXT NOT NULL, outcome_json TEXT NOT NULL,
                    created_at BIGINT NOT NULL
                )
            """)
            db.execute("""
                CREATE OR REPLACE FUNCTION e002_reject_audit_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'audit_append_only'; END;
                $$
            """)
            db.execute("DROP TRIGGER IF EXISTS e002_audit_no_update ON e002_audit")
            db.execute("DROP TRIGGER IF EXISTS e002_audit_no_delete ON e002_audit")
            db.execute("""
                CREATE TRIGGER e002_audit_no_update BEFORE UPDATE ON e002_audit
                FOR EACH ROW EXECUTE FUNCTION e002_reject_audit_mutation()
            """)
            db.execute("""
                CREATE TRIGGER e002_audit_no_delete BEFORE DELETE ON e002_audit
                FOR EACH ROW EXECUTE FUNCTION e002_reject_audit_mutation()
            """)

    def _fault(self, stage: str):
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def reset(self):
        """Test-only helper; use only against a disposable conformance database."""
        with self._connect() as db:
            db.execute("TRUNCATE e002_audit, e002_idempotency_records, e002_outbox, e002_jobs RESTART IDENTITY CASCADE")

    def append_audit(self, event: dict) -> int:
        if not isinstance(event, dict):
            raise ValueError("audit_event_must_be_object")
        event_id = _text(event.get("event_id"), "event_id")
        request_id = _text(event.get("request_id"), "request_id")
        operation_id = _text(event.get("operation_id"), "operation_id")
        decision = event.get("decision")
        if decision not in {"allow", "deny"}:
            raise ValueError("invalid_audit_decision")
        with self._connect() as db:
            row = db.execute(
                """INSERT INTO e002_audit(event_id,request_id,tenant_id,operation_id,
                   decision,reason_code,outcome_json,created_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING sequence""",
                (event_id, request_id, event.get("tenant_id"), operation_id, decision,
                 _text(event.get("reason_code"), "reason_code"),
                 _json(event.get("outcome", {})), int(event.get("created_at", time.time()))),
            ).fetchone()
            return int(row["sequence"])

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

        committed = False
        with self._connect() as db:
            scope = _json([tenant_id, operation_id, idempotency_key])
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (scope,))
            previous = db.execute(
                """SELECT request_hash,outcome_json FROM e002_idempotency_records
                   WHERE tenant_id=%s AND operation_id=%s AND idempotency_key=%s""",
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
                    """INSERT INTO e002_audit(event_id,request_id,tenant_id,operation_id,
                       decision,reason_code,outcome_json,created_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (str(uuid.uuid4()), request_id, tenant_id, operation_id,
                     decision, reason, _json(outcome), now),
                )
                return status, outcome

            job_id, event_id = uuid.uuid4(), uuid.uuid4()
            outcome = {"job_id": str(job_id), "state": "queued"}
            db.execute(
                """INSERT INTO e002_jobs(job_id,tenant_id,operation_id,payload_json,state,created_at)
                   VALUES(%s,%s,%s,%s,'queued',%s)""",
                (job_id, tenant_id, operation_id, payload_json, now),
            )
            self._fault("after_job")
            db.execute(
                """INSERT INTO e002_outbox(event_id,tenant_id,operation_id,job_id,payload_json,created_at)
                   VALUES(%s,%s,%s,%s,%s,%s)""",
                (event_id, tenant_id, operation_id, job_id, outbox_json, now),
            )
            self._fault("after_outbox")
            db.execute(
                """INSERT INTO e002_idempotency_records(tenant_id,operation_id,idempotency_key,
                   request_hash,job_id,outcome_json) VALUES(%s,%s,%s,%s,%s,%s)""",
                (tenant_id, operation_id, idempotency_key, request_hash, job_id, _json(outcome)),
            )
            self._fault("after_idempotency")
            db.execute(
                """INSERT INTO e002_audit(event_id,request_id,tenant_id,operation_id,
                   decision,reason_code,outcome_json,created_at)
                   VALUES(%s,%s,%s,%s,'allow','JOB_ADMITTED',%s,%s)""",
                (uuid.uuid4(), request_id, tenant_id, operation_id, _json(outcome), now),
            )
            self._fault("after_audit")
        committed = True
        self._fault("after_commit")
        return "created", outcome

    def lookup_idempotency(self, tenant_id: str, operation_id: str, key: str):
        with self._connect() as db:
            row = db.execute(
                """SELECT request_hash,outcome_json FROM e002_idempotency_records
                   WHERE tenant_id=%s AND operation_id=%s AND idempotency_key=%s""",
                (tenant_id, operation_id, key),
            ).fetchone()
            return None if row is None else {
                "request_hash": row["request_hash"], "outcome": json.loads(row["outcome_json"])
            }

    def read_job(self, job_id: str):
        with self._connect() as db:
            row = db.execute("SELECT * FROM e002_jobs WHERE job_id=%s", (job_id,)).fetchone()
            return dict(row) if row else None

    def read_outbox_for_job(self, job_id: str):
        with self._connect() as db:
            row = db.execute("SELECT * FROM e002_outbox WHERE job_id=%s", (job_id,)).fetchone()
            return dict(row) if row else None

    def claim_outbox(self, *, consumer: str, limit: int, lease_seconds: int, now: int):
        consumer = _text(consumer, "consumer")
        if type(limit) is not int or limit < 1:
            raise ValueError("invalid_outbox_limit")
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("invalid_outbox_lease")
        if type(now) is not int or now < 0:
            raise ValueError("invalid_outbox_clock")
        with self._connect() as db:
            rows = db.execute(
                """SELECT event_id FROM e002_outbox
                   WHERE delivered_at IS NULL AND (lease_until IS NULL OR lease_until <= %s)
                   ORDER BY created_at,event_id LIMIT %s FOR UPDATE SKIP LOCKED""",
                (now, limit),
            ).fetchall()
            claimed = []
            for row in rows:
                db.execute(
                    """UPDATE e002_outbox SET lease_owner=%s,lease_token=lease_token+1,lease_until=%s
                       WHERE event_id=%s AND delivered_at IS NULL""",
                    (consumer, now + lease_seconds, row["event_id"]),
                )
                claimed.append(db.execute(
                    "SELECT * FROM e002_outbox WHERE event_id=%s", (row["event_id"],)
                ).fetchone())
            return [dict(row) for row in claimed]

    def ack_outbox(self, *, event_id: str, consumer: str, lease_token: int, now: int) -> bool:
        if type(lease_token) is not int or lease_token < 1:
            raise ValueError("invalid_outbox_lease_token")
        with self._connect() as db:
            cursor = db.execute(
                """UPDATE e002_outbox SET delivered_at=%s,lease_owner=NULL,lease_until=NULL
                   WHERE event_id=%s AND lease_owner=%s AND lease_token=%s
                     AND lease_until>%s AND delivered_at IS NULL""",
                (now, event_id, consumer, lease_token, now),
            )
            return cursor.rowcount == 1

    def recover(self) -> dict[str, int]:
        with self._connect() as db:
            return {
                table: int(db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])
                for table in ("e002_jobs", "e002_outbox", "e002_idempotency_records", "e002_audit")
            }

    def metadata(self) -> dict[str, Any]:
        with self._connect() as db:
            version = db.execute("SHOW server_version").fetchone()["server_version"]
            settings = {
                name: db.execute(f"SHOW {name}").fetchone()[name]
                for name in ("fsync", "synchronous_commit", "wal_level")
            }
            return {
                "engine": "postgresql",
                "engine_version": version,
                **settings,
                "canonicalization_version": CANONICALIZATION_VERSION,
                "durability_profile": "fsync=on + synchronous_commit=on",
            }
