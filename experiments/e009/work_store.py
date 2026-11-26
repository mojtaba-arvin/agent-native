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
import threading
import time
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


class JobBackpressure(WorkStoreError):
    pass


class AuditCommitError(WorkStoreError):
    """Atomic audit insertion failed; the job transaction must roll back."""
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

    def __init__(
        self,
        database: str | Path,
        *,
        max_outstanding: int = 1000,
        max_concurrency: int = 16,
        audit_sink: Any | None = None,
        max_submit_batch_size: int = 32,
        max_submit_batch_delay_seconds: float = 0.0005,
    ):
        raw = str(database)
        if raw == ":memory:":
            raise ValueError("file_backed_database_required_for_durable_work")
        if type(max_outstanding) is not int or max_outstanding < 1:
            raise ValueError("max_outstanding_must_be_positive_integer")
        if type(max_concurrency) is not int or max_concurrency < 1:
            raise ValueError("max_concurrency_must_be_positive_integer")
        if max_concurrency > max_outstanding:
            raise ValueError("max_concurrency_cannot_exceed_max_outstanding")
        if type(max_submit_batch_size) is not int or not 1 <= max_submit_batch_size <= 1024:
            raise ValueError("invalid_submit_batch_size")
        if (
            isinstance(max_submit_batch_delay_seconds, bool)
            or not isinstance(max_submit_batch_delay_seconds, (int, float))
            or not 0 <= max_submit_batch_delay_seconds <= 0.050
        ):
            raise ValueError("invalid_submit_batch_delay")
        self.database = str(Path(raw).expanduser().resolve())
        self.max_outstanding = max_outstanding
        self.max_concurrency = max_concurrency
        self.audit_sink = audit_sink
        if audit_sink is not None and getattr(audit_sink, "database", None) != self.database:
            raise ValueError("audit_sink_must_share_work_store_database")
        self.max_submit_batch_size = max_submit_batch_size
        self.max_submit_batch_delay_seconds = float(max_submit_batch_delay_seconds)
        self._submit_condition = threading.Condition()
        self._submit_pending: list[dict[str, Any]] = []
        self._submit_flushing = False
        self._submit_stats_lock = threading.Lock()
        self._submit_batches = 0
        self._committed_submissions = 0
        self._largest_submit_batch = 0
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_inbox_delivery_metrics (
                    consumer_id TEXT PRIMARY KEY,
                    duplicate_deliveries INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        finally:
            connection.close()

    def _enqueue_job_submission(self, item: dict[str, Any]) -> tuple[dict, bool]:
        with self._submit_condition:
            while len(self._submit_pending) >= self.max_submit_batch_size * 128:
                self._submit_condition.wait()
            self._submit_pending.append(item)
            leader = not self._submit_flushing
            if leader:
                self._submit_flushing = True
            self._submit_condition.notify_all()

        if leader:
            self._flush_job_submission_batches()
        else:
            item["done"].wait()

        if item["error"] is not None:
            raise item["error"]
        return item["result"]

    def _flush_job_submission_batches(self) -> None:
        while True:
            with self._submit_condition:
                deadline = time.monotonic() + self.max_submit_batch_delay_seconds
                while (
                    len(self._submit_pending) < self.max_submit_batch_size
                    and self.max_submit_batch_delay_seconds > 0
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._submit_condition.wait(remaining)
                batch = self._submit_pending[: self.max_submit_batch_size]
                del self._submit_pending[: len(batch)]
                self._submit_condition.notify_all()

            if batch:
                try:
                    self._commit_job_submission_batch(batch)
                except Exception:
                    for item in batch:
                        if item["error"] is None:
                            item["error"] = AuditCommitError("atomic_job_batch_commit_failed")
                for item in batch:
                    item["done"].set()

            with self._submit_condition:
                if not self._submit_pending:
                    self._submit_flushing = False
                    self._submit_condition.notify_all()
                    return

    def _commit_job_submission_batch(self, batch: list[dict[str, Any]]) -> None:
        connection = self._connect()
        successful: list[dict[str, Any]] = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            for index, item in enumerate(batch):
                savepoint = f"job_submission_{index}"
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    previous = connection.execute(
                        """
                        SELECT * FROM durable_jobs
                        WHERE tenant_id = ? AND idempotency_key = ?
                        """,
                        (item["tenant_id"], item["idempotency_key"]),
                    ).fetchone()
                    if previous is not None:
                        if previous["request_sha256"] != item["request_digest"]:
                            raise JobConflict("job_idempotency_key_reused_with_different_request")
                        row = previous
                        replayed = True
                    else:
                        active = connection.execute(
                            """
                            SELECT COUNT(*) AS count FROM durable_jobs
                            WHERE state IN ('queued', 'running', 'cancellation_requested')
                            """
                        ).fetchone()["count"]
                        if active >= self.max_outstanding:
                            raise JobBackpressure("durable_work_queue_at_capacity")

                        task_id = str(uuid.uuid4())
                        row = connection.execute(
                            """
                            INSERT INTO durable_jobs(
                                task_id, tenant_id, task_type, payload_json, idempotency_key,
                                request_sha256, state, available_at, deadline_at, attempts,
                                max_attempts, lease_token, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, 0, ?, 0, ?, ?)
                            RETURNING *
                            """,
                            (
                                task_id, item["tenant_id"], item["task_type"],
                                item["payload_json"], item["idempotency_key"],
                                item["request_digest"], item["now"], item["deadline_at"],
                                item["max_attempts"], item["now"], item["now"],
                            ),
                        ).fetchone()
                        self._insert_event(
                            connection,
                            tenant_id=item["tenant_id"],
                            topic="work.submitted",
                            payload={
                                "payload": {"task_id": task_id, "task_type": item["task_type"]},
                                "state_key": "work.submitted",
                                "amount": 1,
                            },
                            now=item["now"],
                        )
                        replayed = False

                    try:
                        self.audit_sink.write_in_transaction(connection, item["audit_event"])
                    except Exception as error:
                        raise AuditCommitError("atomic_audit_insert_failed") from error

                    item["result"] = (self._job(row), replayed)
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    successful.append(item)
                except (JobConflict, JobBackpressure, AuditCommitError) as error:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                    item["error"] = error

            connection.commit()
            for item in successful:
                self.audit_sink.note_transactional_commit()
                item["audit_receipt"].mark_committed()
            with self._submit_stats_lock:
                if successful:
                    self._submit_batches += 1
                    self._committed_submissions += len(successful)
                    self._largest_submit_batch = max(
                        self._largest_submit_batch, len(successful)
                    )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def metrics(self) -> dict[str, int]:
        """Return process-local submission batch counters for diagnostics."""
        with self._submit_stats_lock:
            return {
                "submit_batches": self._submit_batches,
                "committed_submissions": self._committed_submissions,
                "largest_submit_batch": self._largest_submit_batch,
            }

    def recovery_metrics(self, *, now: int | None = None) -> dict[str, Any]:
        """Read persisted recovery counters without taking a write transaction."""
        if now is not None:
            _integer(now, "now")
        connection = self._connect()
        try:
            connection.execute("PRAGMA query_only = ON")
            job_states = {
                row["state"]: int(row["count"])
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS count FROM durable_jobs GROUP BY state"
                )
            }
            outbox_states = {
                row["status"]: int(row["count"])
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM durable_outbox GROUP BY status"
                )
            }
            job_rows = connection.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(attempts), 0) AS attempts, "
                "COALESCE(SUM(CASE WHEN attempts > 1 THEN 1 ELSE 0 END), 0) AS multi_attempt "
                "FROM durable_jobs"
            ).fetchone()
            outbox_rows = connection.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(attempts), 0) AS attempts, "
                "COALESCE(SUM(CASE WHEN attempts > 1 THEN attempts - 1 ELSE 0 END), 0) AS redeliveries "
                "FROM durable_outbox"
            ).fetchone()
            inbox_rows = connection.execute(
                "SELECT COUNT(*) AS total FROM durable_inbox"
            ).fetchone()
            duplicate_rows = connection.execute(
                "SELECT COALESCE(SUM(duplicate_deliveries), 0) AS total "
                "FROM durable_inbox_delivery_metrics"
            ).fetchone()
            expired_leases = 0
            if now is not None:
                expired_leases = int(connection.execute(
                    "SELECT COUNT(*) AS total FROM durable_jobs "
                    "WHERE state IN ('running', 'cancellation_requested') "
                    "AND lease_until IS NOT NULL AND lease_until <= ?",
                    (now,),
                ).fetchone()["total"])
            return {
                "jobs": {
                    "total": int(job_rows["total"]),
                    "by_state": job_states,
                    "claim_attempts": int(job_rows["attempts"]),
                    "multi_attempt_jobs": int(job_rows["multi_attempt"]),
                    "expired_active_leases": expired_leases,
                },
                "outbox": {
                    "total": int(outbox_rows["total"]),
                    "by_state": outbox_states,
                    "claim_attempts": int(outbox_rows["attempts"]),
                    "redeliveries": int(outbox_rows["redeliveries"]),
                },
                "inbox": {
                    "messages": int(inbox_rows["total"]),
                    "duplicate_deliveries": int(duplicate_rows["total"]),
                },
            }
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
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
        audit_event: dict | None = None,
        audit_receipt: Any | None = None,
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
        if audit_event is not None and (
            self.audit_sink is None
            or audit_receipt is None
            or not callable(getattr(self.audit_sink, "write_in_transaction", None))
        ):
            raise AuditCommitError("atomic_audit_sink_and_receipt_required")
        payload_json = _json(payload)
        request_digest = _digest({"task_type": task_type, "payload": payload})

        if audit_event is not None:
            item = {
                "tenant_id": tenant_id,
                "task_type": task_type,
                "payload_json": payload_json,
                "idempotency_key": idempotency_key,
                "request_digest": request_digest,
                "now": now,
                "deadline_at": deadline_at,
                "max_attempts": max_attempts,
                "audit_event": dict(audit_event),
                "audit_receipt": audit_receipt,
                "done": threading.Event(),
                "result": None,
                "error": None,
            }
            return self._enqueue_job_submission(item)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT * FROM durable_jobs
                WHERE tenant_id = ? AND idempotency_key = ?
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["request_sha256"] != request_digest:
                    raise JobConflict("job_idempotency_key_reused_with_different_request")
                row = previous
                if audit_event is not None:
                    try:
                        self.audit_sink.write_in_transaction(connection, audit_event)
                    except Exception as error:
                        raise AuditCommitError("atomic_audit_insert_failed") from error
                connection.commit()
                if audit_event is not None:
                    self.audit_sink.note_transactional_commit()
                    audit_receipt.mark_committed()
                return self._job(row), True

            active = connection.execute(
                """
                SELECT COUNT(*) AS count FROM durable_jobs
                WHERE state IN ('queued', 'running', 'cancellation_requested')
                """
            ).fetchone()["count"]
            if active >= self.max_outstanding:
                raise JobBackpressure("durable_work_queue_at_capacity")

            task_id = str(uuid.uuid4())
            row = connection.execute(
                """
                INSERT INTO durable_jobs(
                    task_id, tenant_id, task_type, payload_json, idempotency_key,
                    request_sha256, state, available_at, deadline_at, attempts,
                    max_attempts, lease_token, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, 0, ?, 0, ?, ?)
                RETURNING *
                """,
                (
                    task_id, tenant_id, task_type, payload_json, idempotency_key,
                    request_digest, now, deadline_at, max_attempts, now, now,
                ),
            ).fetchone()
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
            if audit_event is not None:
                try:
                    self.audit_sink.write_in_transaction(connection, audit_event)
                except Exception as error:
                    raise AuditCommitError("atomic_audit_insert_failed") from error
            connection.commit()
            if audit_event is not None:
                self.audit_sink.note_transactional_commit()
                audit_receipt.mark_committed()
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
            # Most worker polls are idle. Probe with autocommit reads first so
            # an empty queue does not acquire SQLite's single-writer lock.
            expired_probe = connection.execute(
                """
                SELECT task_id FROM durable_jobs
                WHERE state = 'queued' AND deadline_at <= ?
                ORDER BY created_at LIMIT 1
                """,
                (now,),
            ).fetchone()
            if expired_probe is None:
                running_probe = connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM durable_jobs
                    WHERE state IN ('running', 'cancellation_requested')
                    """
                ).fetchone()["count"]
                if running_probe >= self.max_concurrency:
                    return None
                runnable_probe = connection.execute(
                    """
                    SELECT task_id FROM durable_jobs
                    WHERE state = 'queued' AND available_at <= ? AND deadline_at > ?
                      AND attempts < max_attempts
                    ORDER BY available_at, created_at, task_id LIMIT 1
                    """,
                    (now, now),
                ).fetchone()
                if runnable_probe is None:
                    return None

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
            running = connection.execute(
                """
                SELECT COUNT(*) AS count FROM durable_jobs
                WHERE state IN ('running', 'cancellation_requested')
                """
            ).fetchone()["count"]
            if running >= self.max_concurrency:
                connection.commit()
                return None

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

    def request_expired_job_stops(self, *, now: int) -> int:
        """Fence expired leases and request an explicit worker stop acknowledgement.

        Lease expiry is not treated as proof that the worker process has stopped.
        The worker slot remains represented until acknowledge_stopped is committed.
        """
        _integer(now, "now")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT task_id FROM durable_jobs
                WHERE state = 'running' AND lease_until <= ?
                """,
                (now,),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    UPDATE durable_jobs
                    SET state = 'cancellation_requested',
                        terminal_reason = 'lease_expired', updated_at = ?
                    WHERE task_id = ? AND state = 'running'
                    """,
                    (now, row["task_id"]),
                )
            connection.commit()
            return len(rows)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def worker_crashed(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_token: int,
        now: int,
    ) -> dict:
        """Record a trusted supervisor's confirmation that a worker has stopped."""
        return self.acknowledge_stopped(
            task_id=task_id,
            worker_id=worker_id,
            lease_token=lease_token,
            now=now,
            reason="worker_crashed",
        )

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
            # Avoid BEGIN IMMEDIATE when the relay has nothing to lease or
            # recover; idle polling must not contend with job admissions.
            expired_probe = connection.execute(
                """
                SELECT event_id FROM durable_outbox
                WHERE status = 'leased' AND lease_until <= ? LIMIT 1
                """,
                (now,),
            ).fetchone()
            pending_probe = connection.execute(
                """
                SELECT event_id FROM durable_outbox
                WHERE status = 'pending' AND available_at <= ?
                  AND attempts < max_attempts LIMIT 1
                """,
                (now,),
            ).fetchone()
            if expired_probe is None and pending_probe is None:
                return None

            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                """
                SELECT event_id, attempts, max_attempts
                FROM durable_outbox
                WHERE status = 'leased' AND lease_until <= ?
                """,
                (now,),
            ).fetchall()
            for item in expired:
                connection.execute(
                    """
                    UPDATE durable_outbox
                    SET status = ?, available_at = ?, lease_owner = NULL,
                        lease_until = NULL,
                        last_error = COALESCE(last_error, 'relay_lease_expired')
                    WHERE event_id = ? AND status = 'leased'
                    """,
                    (
                        "failed" if item["attempts"] >= item["max_attempts"] else "pending",
                        now,
                        item["event_id"],
                    ),
                )
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
                connection.execute(
                    """
                    INSERT INTO durable_inbox_delivery_metrics(consumer_id, duplicate_deliveries)
                    VALUES (?, 1)
                    ON CONFLICT(consumer_id)
                    DO UPDATE SET duplicate_deliveries = duplicate_deliveries + 1
                    """,
                    (consumer_id,),
                )
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
