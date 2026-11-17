"""Durable jobs and transactional outbox/inbox over the E-009 shared database.

This is a single-node SQLite semantic implementation of E-003/E-006/E-008
boundaries. Leases are fenced. Running cancellation retains ownership until
the worker acknowledges that it has stopped. Outbox delivery is at-least-once;
the inbox makes the local consumer effect idempotent.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


class WorkStoreError(RuntimeError):
    pass


class WorkNotFound(WorkStoreError):
    pass


class StaleJobLease(WorkStoreError):
    pass


class StaleOutboxLease(WorkStoreError):
    pass


class JobConflict(WorkStoreError):
    pass


class InboxConflict(WorkStoreError):
    pass


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"invalid_{name}")
    return value


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


class DurableWorkStore:
    """Transactional job, lease, outbox, and inbox store on the Catalog DB."""

    def __init__(self, database: str | Path):
        raw = str(database)
        if raw == ":memory:":
            raise ValueError("file_backed_database_required_for_durable_work")
        self.database = str(Path(raw).expanduser().resolve())

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        tenant_id: str,
        topic: str,
        payload: dict,
        now: int,
        max_attempts: int = 8,
    ) -> str:
        event_id = str(uuid.uuid4())
        connection.execute(
            """
            INSERT INTO durable_outbox(
                event_id, tenant_id, topic, payload_json, status, available_at,
                attempts, max_attempts, created_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, 0, ?, ?)
            """,
            (event_id, tenant_id, topic, _json(payload), now, max_attempts, now),
        )
        return event_id

    @staticmethod
    def _job(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        if result.get("result_json") is not None:
            result["result"] = json.loads(result.pop("result_json"))
        else:
            result.pop("result_json", None)
            result["result"] = None
        return result

    def submit_job(
        self,
        *,
        tenant_id: str,
        task_type: str,
        payload: dict,
        idempotency_key: str,
        now: int,
        deadline_at: int,
        max_attempts: int = 3,
    ) -> tuple[dict, bool]:
        tenant_id = _text(tenant_id, "tenant_id")
        task_type = _text(task_type, "task_type")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        _integer(now, "now")
        _integer(deadline_at, "deadline_at", minimum=1)
        _integer(max_attempts, "max_attempts", minimum=1)
        if deadline_at <= now:
            raise ValueError("deadline_must_be_in_the_future")
        if not isinstance(payload, dict):
            raise ValueError("job_payload_must_be_object")
        payload_json = _json(payload)
        request_digest = _digest({"task_type": task_type, "payload": payload})

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT task_id, request_sha256
                FROM durable_jobs
                WHERE tenant_id = ? AND idempotency_key = ?
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["request_sha256"] != request_digest:
                    raise JobConflict("job_idempotency_key_reused_with_different_request")
                row = connection.execute(
                    "SELECT * FROM durable_jobs WHERE task_id = ?",
                    (previous["task_id"],),
                ).fetchone()
                connection.commit()
                return self._job(row), True

            task_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO durable_jobs(
                    task_id, tenant_id, task_type, payload_json, idempotency_key,
                    request_sha256, state, available_at, deadline_at, attempts,
                    max_attempts, lease_token, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, 0, ?, 0, ?, ?)
                """,
                (
                    task_id, tenant_id, task_type, payload_json, idempotency_key,
                    request_digest, now, deadline_at, max_attempts, now, now,
                ),
            )
            self._insert_event(
                connection,
                tenant_id=tenant_id,
                topic="work.submitted",
                payload={
                    "payload": {"task_id": task_id, "task_type": task_type},
                    "state_key": "work.submitted",
                    "amount": 1,
                },
                now=now,
            )
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
            return self._job(row), False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_job(self, *, tenant_id: str, task_id: str) -> dict | None:
        tenant_id = _text(tenant_id, "tenant_id")
        task_id = _text(task_id, "task_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE tenant_id = ? AND task_id = ?",
                (tenant_id, task_id),
            ).fetchone()
            return self._job(row)
        finally:
            connection.close()

    def claim_job(
        self,
        *,
        worker_id: str,
        now: int,
        lease_seconds: int,
    ) -> dict | None:
        worker_id = _text(worker_id, "worker_id")
        _integer(now, "now")
        _integer(lease_seconds, "lease_seconds", minimum=1)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                """
                SELECT task_id, tenant_id, task_type
                FROM durable_jobs
                WHERE state = 'queued' AND deadline_at <= ?
                ORDER BY created_at LIMIT 1
                """,
                (now,),
            ).fetchone()
            if expired is not None:
                connection.execute(
                    """
                    UPDATE durable_jobs SET state = 'expired',
                        terminal_reason = 'deadline', updated_at = ?
                    WHERE task_id = ? AND state = 'queued'
                    """,
                    (now, expired["task_id"]),
                )
                self._insert_event(
                    connection,
                    tenant_id=expired["tenant_id"],
                    topic="work.expired",
                    payload={
                        "payload": {"task_id": expired["task_id"], "task_type": expired["task_type"]},
                        "state_key": "work.expired",
                        "amount": 1,
                    },
                    now=now,
                )
            row = connection.execute(
                """
                SELECT task_id FROM durable_jobs
                WHERE state = 'queued' AND available_at <= ? AND deadline_at > ?
                  AND attempts < max_attempts
                ORDER BY available_at, created_at, task_id LIMIT 1
                """,
                (now, now),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            task_id = row["task_id"]
            updated = connection.execute(
                """
                UPDATE durable_jobs
                SET state = 'running', attempts = attempts + 1,
                    lease_owner = ?, lease_until = ?, lease_token = lease_token + 1,
                    updated_at = ?
                WHERE task_id = ? AND state = 'queued'
                """,
                (worker_id, now + lease_seconds, now, task_id),
            )
            if updated.rowcount != 1:
                raise WorkStoreError("job_claim_lost_inside_serialized_transaction")
            claimed = connection.execute(
                "SELECT * FROM durable_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
            return self._job(claimed)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def complete_job(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_token: int,
        now: int,
        result: dict,
    ) -> dict:
        task_id = _text(task_id, "task_id")
        worker_id = _text(worker_id, "worker_id")
        _integer(lease_token, "lease_token", minimum=1)
        _integer(now, "now")
        if not isinstance(result, dict):
            raise ValueError("job_result_must_be_object")
        result_json = _json(result)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT tenant_id, task_type, state, lease_owner, lease_until,
                       lease_token, deadline_at
                FROM durable_jobs WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if (
                row is None or row["state"] != "running"
                or row["lease_owner"] != worker_id
                or row["lease_token"] != lease_token
                or row["lease_until"] is None
                or row["lease_until"] <= now
            ):
                raise StaleJobLease("job_lease_missing_expired_or_fenced")
            if row["deadline_at"] <= now:
                raise StaleJobLease("job_deadline_expired")
            connection.execute(
                """
                UPDATE durable_jobs
                SET state = 'completed', result_json = ?, lease_owner = NULL,
                    lease_until = NULL, terminal_reason = 'completed', updated_at = ?
                WHERE task_id = ?
                """,
                (result_json, now, task_id),
            )
            self._insert_event(
                connection,
                tenant_id=row["tenant_id"],
                topic="work.completed",
                payload={
                    "payload": {
                        "task_id": task_id,
                        "task_type": row["task_type"],
                        "result": result,
                    },
                    "state_key": row["task_type"],
                    "amount": 1,
                },
                now=now,
            )
            updated = connection.execute(
                "SELECT * FROM durable_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
            return self._job(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def fail_job(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_token: int,
        now: int,
        error_code: str,
        retry_delay: int = 1,
    ) -> dict:
        task_id = _text(task_id, "task_id")
        worker_id = _text(worker_id, "worker_id")
        error_code = _text(error_code, "error_code")
        _integer(lease_token, "lease_token", minimum=1)
        _integer(now, "now")
        _integer(retry_delay, "retry_delay")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM durable_jobs
                WHERE task_id = ? AND state = 'running'
                  AND lease_owner = ? AND lease_token = ? AND lease_until > ?
                """,
                (task_id, worker_id, lease_token, now),
            ).fetchone()
            if row is None:
                raise StaleJobLease("job_lease_missing_expired_or_fenced")
            if row["deadline_at"] <= now:
                state = "expired"
                available_at = now
                topic = "work.expired"
            elif row["attempts"] >= row["max_attempts"]:
                state = "failed"
                available_at = now
                topic = "work.failed"
            else:
                state = "queued"
                available_at = now + retry_delay
                topic = None
            connection.execute(
                """
                UPDATE durable_jobs
                SET state = ?, available_at = ?, lease_owner = NULL,
                    lease_until = NULL, last_error = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (state, available_at, error_code, now, task_id),
            )
            if topic:
                self._insert_event(
                    connection,
                    tenant_id=row["tenant_id"],
                    topic=topic,
                    payload={
                        "payload": {"task_id": task_id, "task_type": row["task_type"], "error": error_code},
                        "state_key": topic,
                        "amount": 1,
                    },
                    now=now,
                )
            updated = connection.execute(
                "SELECT * FROM durable_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
            return self._job(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def cancel_job(self, *, tenant_id: str, task_id: str, now: int) -> dict | None:
        tenant_id = _text(tenant_id, "tenant_id")
        task_id = _text(task_id, "task_id")
        _integer(now, "now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM durable_jobs WHERE tenant_id = ? AND task_id = ?",
                (tenant_id, task_id),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            if row["state"] == "queued":
                connection.execute(
                    """
                    UPDATE durable_jobs SET state = 'cancelled',
                        terminal_reason = 'cancelled', updated_at = ?
                    WHERE task_id = ?
                    """,
                    (now, task_id),
                )
                self._insert_event(
                    connection,
                    tenant_id=tenant_id,
                    topic="work.cancelled",
                    payload={
                        "payload": {"task_id": task_id, "task_type": row["task_type"]},
                        "state_key": "work.cancelled",
                        "amount": 1,
                    },
                    now=now,
                )
            elif row["state"] == "running":
                connection.execute(
                    """
                    UPDATE durable_jobs SET state = 'cancellation_requested',
                        terminal_reason = 'cancelled', updated_at = ?
                    WHERE task_id = ?
                    """,
                    (now, task_id),
                )
            updated = connection.execute(
                "SELECT * FROM durable_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
            return self._job(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def request_expirations(self, *, now: int) -> dict[str, int]:
        _integer(now, "now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            queued = connection.execute(
                """
                SELECT task_id, tenant_id, task_type FROM durable_jobs
                WHERE state = 'queued' AND deadline_at <= ?
                """,
                (now,),
            ).fetchall()
            for row in queued:
                connection.execute(
                    """
                    UPDATE durable_jobs SET state = 'expired',
                        terminal_reason = 'deadline', updated_at = ?
                    WHERE task_id = ?
                    """,
                    (now, row["task_id"]),
                )
                self._insert_event(
                    connection, tenant_id=row["tenant_id"], topic="work.expired",
                    payload={
                        "payload": {"task_id": row["task_id"], "task_type": row["task_type"]},
                        "state_key": "work.expired", "amount": 1,
                    }, now=now,
                )
            running = connection.execute(
                """
                SELECT task_id FROM durable_jobs
                WHERE state = 'running' AND deadline_at <= ?
                """,
                (now,),
            ).fetchall()
            for row in running:
                connection.execute(
                    """
                    UPDATE durable_jobs SET state = 'cancellation_requested',
                        terminal_reason = 'deadline', updated_at = ?
                    WHERE task_id = ?
                    """,
                    (now, row["task_id"]),
                )
            connection.commit()
            return {"queued_expired": len(queued), "running_stop_requested": len(running)}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def acknowledge_stopped(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_token: int,
        now: int,
        reason: str = "worker_stopped",
    ) -> dict:
        task_id = _text(task_id, "task_id")
        worker_id = _text(worker_id, "worker_id")
        reason = _text(reason, "reason")
        _integer(lease_token, "lease_token", minimum=1)
        _integer(now, "now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM durable_jobs
                WHERE task_id = ? AND state IN ('running', 'cancellation_requested')
                  AND lease_owner = ? AND lease_token = ?
                """,
                (task_id, worker_id, lease_token),
            ).fetchone()
            if row is None:
                raise StaleJobLease("stopped_ack_missing_or_fenced")
            terminal_reason = row["terminal_reason"]
            if row["state"] == "cancellation_requested" and terminal_reason == "cancelled":
                state = "cancelled"
                topic = "work.cancelled"
            elif row["state"] == "cancellation_requested" and terminal_reason == "deadline":
                state = "expired"
                topic = "work.expired"
            elif row["deadline_at"] <= now:
                state = "expired"
                topic = "work.expired"
            elif row["attempts"] >= row["max_attempts"]:
                state = "failed"
                topic = "work.failed"
            else:
                state = "queued"
                topic = None
            connection.execute(
                """
                UPDATE durable_jobs
                SET state = ?, available_at = ?, lease_owner = NULL,
                    lease_until = NULL, terminal_reason = ?, last_error = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    state, now, state if state in {"cancelled", "expired", "failed"} else None,
                    reason, now, task_id,
                ),
            )
            if topic:
                self._insert_event(
                    connection, tenant_id=row["tenant_id"], topic=topic,
                    payload={
                        "payload": {"task_id": task_id, "task_type": row["task_type"], "reason": reason},
                        "state_key": topic, "amount": 1,
                    }, now=now,
                )
            updated = connection.execute(
                "SELECT * FROM durable_jobs WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
            return self._job(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_outbox(
        self,
        *,
        relay_id: str,
        now: int,
        lease_seconds: int,
    ) -> dict | None:
        relay_id = _text(relay_id, "relay_id")
        _integer(now, "now")
        _integer(lease_seconds, "lease_seconds", minimum=1)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM durable_outbox
                WHERE status = 'pending' AND available_at <= ?
                  AND attempts < max_attempts
                ORDER BY available_at, created_at, event_id LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE durable_outbox
                SET status = 'leased', attempts = attempts + 1,
                    lease_owner = ?, lease_until = ?, lease_token = lease_token + 1
                WHERE event_id = ? AND status = 'pending'
                """,
                (relay_id, now + lease_seconds, row["event_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM durable_outbox WHERE event_id = ?",
                (row["event_id"],),
            ).fetchone()
            connection.commit()
            result = dict(claimed)
            result["payload"] = json.loads(result.pop("payload_json"))
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def ack_outbox(
        self,
        *,
        event_id: str,
        relay_id: str,
        lease_token: int,
        now: int,
    ) -> None:
        event_id = _text(event_id, "event_id")
        relay_id = _text(relay_id, "relay_id")
        _integer(lease_token, "lease_token", minimum=1)
        _integer(now, "now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE durable_outbox
                SET status = 'published', lease_owner = NULL, lease_until = NULL
                WHERE event_id = ? AND status = 'leased' AND lease_owner = ?
                  AND lease_token = ? AND lease_until > ?
                """,
                (event_id, relay_id, lease_token, now),
            )
            if updated.rowcount != 1:
                raise StaleOutboxLease("outbox_lease_missing_expired_or_fenced")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def retry_outbox(
        self,
        *,
        event_id: str,
        relay_id: str,
        lease_token: int,
        now: int,
        delay_seconds: int,
        error_code: str,
    ) -> bool:
        event_id = _text(event_id, "event_id")
        relay_id = _text(relay_id, "relay_id")
        error_code = _text(error_code, "error_code")
        _integer(lease_token, "lease_token", minimum=1)
        _integer(now, "now")
        _integer(delay_seconds, "delay_seconds")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT attempts, max_attempts FROM durable_outbox
                WHERE event_id = ? AND status = 'leased' AND lease_owner = ?
                  AND lease_token = ? AND lease_until > ?
                """,
                (event_id, relay_id, lease_token, now),
            ).fetchone()
            if row is None:
                raise StaleOutboxLease("outbox_lease_missing_expired_or_fenced")
            terminal = row["attempts"] >= row["max_attempts"]
            connection.execute(
                """
                UPDATE durable_outbox
                SET status = ?, available_at = ?, lease_owner = NULL,
                    lease_until = NULL, last_error = ?
                WHERE event_id = ?
                """,
                ("failed" if terminal else "pending", now + delay_seconds, error_code, event_id),
            )
            connection.commit()
            return not terminal
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def consume_delta_event(
        self,
        *,
        consumer_id: str,
        event_id: str,
        payload: dict,
        now: int,
    ) -> dict:
        consumer_id = _text(consumer_id, "consumer_id")
        event_id = _text(event_id, "event_id")
        _integer(now, "now")
        if not isinstance(payload, dict) or set(payload) != {"payload", "state_key", "amount"}:
            raise ValueError("invalid_consumer_event_envelope")
        if not isinstance(payload["payload"], dict):
            raise ValueError("consumer_payload_must_be_object")
        state_key = _text(payload["state_key"], "state_key")
        amount = _integer(payload["amount"], "amount")
        payload_json = _json(payload)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT payload_sha256 FROM durable_inbox
                WHERE consumer_id = ? AND event_id = ?
                """,
                (consumer_id, event_id),
            ).fetchone()
            if previous is not None:
                if previous["payload_sha256"] != payload_hash:
                    raise InboxConflict("event_id_reused_with_different_envelope")
                total = connection.execute(
                    """
                    SELECT total FROM consumer_totals
                    WHERE consumer_id = ? AND state_key = ?
                    """,
                    (consumer_id, state_key),
                ).fetchone()
                connection.commit()
                return {"duplicate": True, "total": total["total"] if total else 0}

            connection.execute(
                """
                INSERT INTO durable_inbox(
                    consumer_id, event_id, payload_sha256, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (consumer_id, event_id, payload_hash, payload_json, now),
            )
            connection.execute(
                """
                INSERT INTO consumer_totals(consumer_id, state_key, total)
                VALUES (?, ?, ?)
                ON CONFLICT(consumer_id, state_key)
                DO UPDATE SET total = total + excluded.total
                """,
                (consumer_id, state_key, amount),
            )
            total = connection.execute(
                """
                SELECT total FROM consumer_totals
                WHERE consumer_id = ? AND state_key = ?
                """,
                (consumer_id, state_key),
            ).fetchone()["total"]
            connection.commit()
            return {"duplicate": False, "total": total}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def consumer_total(self, *, consumer_id: str, state_key: str) -> int:
        consumer_id = _text(consumer_id, "consumer_id")
        state_key = _text(state_key, "state_key")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT total FROM consumer_totals WHERE consumer_id = ? AND state_key = ?",
                (consumer_id, state_key),
            ).fetchone()
            return int(row["total"]) if row is not None else 0
        finally:
            connection.close()

    def outbox_counts(self) -> dict[str, int]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM durable_outbox GROUP BY status"
            ).fetchall()
            return {row["status"]: row["count"] for row in rows}
        finally:
            connection.close()
