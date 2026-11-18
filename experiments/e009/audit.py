"""Durable, append-only application audit sink for the E-009 SQLite reference kernel.

This is a single-node persistence component, not a tamper-proof remote audit service.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


_REQUIRED_FIELDS = {
    "principal_id",
    "tenant_id",
    "operation",
    "resource",
    "requested_effects",
    "decision",
    "reason_code",
    "request_id",
    "timestamp",
}


class SQLiteAuditSink:
    """Append audit events with bounded synchronous group commit.

    Callers do not return until their event's transaction has committed under
    SQLite synchronous=FULL. Concurrent callers may share one WAL commit;
    an event is never acknowledged merely because it entered the in-memory
    batch. A failed transaction fails every caller in that batch closed. The
    performance pilot keeps FULL durability enabled throughout measurement.
    Batch counters are process-local diagnostics; they never gate or bypass commits.
    The pilot varies the collection window while retaining the same commit contract.
    Every reported latency sample includes the durable audit decision path.
    The durable job path shares its commit with the audit row and outbox event.
    Idle worker and relay polls are read-only until actual work is available.
    Durable job admission uses bounded synchronous commit batching.
    """

    def __init__(
        self,
        database: str | Path,
        *,
        max_batch_size: int = 32,
        max_batch_delay_seconds: float = 0.002,
    ):
        raw = str(database)
        if raw == ":memory:":
            raise ValueError("file_backed_audit_database_required")
        if type(max_batch_size) is not int or not 1 <= max_batch_size <= 1024:
            raise ValueError("invalid_audit_batch_size")
        if (
            isinstance(max_batch_delay_seconds, bool)
            or not isinstance(max_batch_delay_seconds, (int, float))
            or not 0 <= max_batch_delay_seconds <= 0.050
        ):
            raise ValueError("invalid_audit_batch_delay")
        self.database = str(Path(raw).expanduser().resolve())
        self.max_batch_size = max_batch_size
        self.max_batch_delay_seconds = float(max_batch_delay_seconds)
        self._condition = threading.Condition()
        self._pending: list[dict[str, Any]] = []
        self._flushing = False
        self._stats_lock = threading.Lock()
        self._committed_batches = 0
        self._committed_events = 0
        self._largest_batch = 0
        self._transactional_events = 0
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL CHECK(typeof(timestamp) = 'integer'),
                    principal_id TEXT,
                    tenant_id TEXT,
                    operation TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    requested_effects_json TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('allow', 'deny')),
                    reason_code TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS audit_events_request_idx
                    ON audit_events(request_id, event_id);

                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events_are_append_only');
                END;

                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events_are_append_only');
                END;
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _prepare(event: dict[str, Any]) -> tuple:
        if not isinstance(event, dict) or set(event) != _REQUIRED_FIELDS:
            raise ValueError("invalid_audit_event_fields")

        for name in ("operation", "resource", "decision", "reason_code", "request_id"):
            if not isinstance(event[name], str) or not event[name].strip():
                raise ValueError(f"invalid_audit_{name}")
        for name in ("principal_id", "tenant_id"):
            if event[name] is not None and (
                not isinstance(event[name], str) or not event[name].strip()
            ):
                raise ValueError(f"invalid_audit_{name}")
        if type(event["timestamp"]) is not int or event["timestamp"] < 0:
            raise ValueError("invalid_audit_timestamp")
        if event["decision"] not in {"allow", "deny"}:
            raise ValueError("invalid_audit_decision")
        effects = event["requested_effects"]
        if (
            not isinstance(effects, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in effects)
        ):
            raise ValueError("invalid_audit_requested_effects")

        effects_json = json.dumps(
            sorted(set(effects)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return (
            event["request_id"],
            event["timestamp"],
            event["principal_id"],
            event["tenant_id"],
            event["operation"],
            event["resource"],
            effects_json,
            event["decision"],
            event["reason_code"],
        )

    def write_in_transaction(self, connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        """Insert an audit event into a caller-owned transaction.

        The caller owns BEGIN/COMMIT and must use the same database. This is
        used for atomic durable-job admission so job, outbox, idempotency
        identity, and authorization audit share one FULL-synchronous commit.
        """
        connection.execute(
            """
            INSERT INTO audit_events(
                request_id, timestamp, principal_id, tenant_id, operation,
                resource, requested_effects_json, decision, reason_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._prepare(event),
        )

    def note_transactional_commit(self) -> None:
        """Count an audit row only after the caller confirms transaction commit."""
        with self._stats_lock:
            self._transactional_events += 1

    def _write_batch(self, batch: list[dict[str, Any]]) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO audit_events(
                    request_id, timestamp, principal_id, tenant_id, operation,
                    resource, requested_effects_json, decision, reason_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [item["row"] for item in batch],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _flush_as_leader(self) -> None:
        while True:
            with self._condition:
                deadline = time.monotonic() + self.max_batch_delay_seconds
                while (
                    len(self._pending) < self.max_batch_size
                    and self.max_batch_delay_seconds > 0
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
                batch = self._pending[: self.max_batch_size]
                del self._pending[: len(batch)]

            if batch:
                error = None
                try:
                    self._write_batch(batch)
                    with self._stats_lock:
                        self._committed_batches += 1
                        self._committed_events += len(batch)
                        self._largest_batch = max(self._largest_batch, len(batch))
                except Exception as caught:
                    error = caught
                for item in batch:
                    item["error"] = error
                    item["done"].set()

            with self._condition:
                if not self._pending:
                    self._flushing = False
                    self._condition.notify_all()
                    return

    def __call__(self, event: dict[str, Any]) -> None:
        item = {"row": self._prepare(event), "done": threading.Event(), "error": None}
        with self._condition:
            self._pending.append(item)
            leader = not self._flushing
            if leader:
                self._flushing = True
            self._condition.notify_all()

        if leader:
            self._flush_as_leader()
        else:
            item["done"].wait()

        if item["error"] is not None:
            raise OSError("audit_batch_commit_failed") from item["error"]

    def metrics(self) -> dict[str, int]:
        """Return process-local counters; these are diagnostics, not durable state."""
        with self._stats_lock:
            return {
                "committed_batches": self._committed_batches,
                "committed_events": self._committed_events,
                "largest_batch": self._largest_batch,
                "transactional_events": self._transactional_events,
            }

    def list_events(self, *, request_id: str | None = None) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            if request_id is None:
                rows = connection.execute(
                    "SELECT * FROM audit_events ORDER BY event_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM audit_events WHERE request_id = ? ORDER BY event_id",
                    (request_id,),
                ).fetchall()
            return [
                {
                    "event_id": row["event_id"],
                    "request_id": row["request_id"],
                    "timestamp": row["timestamp"],
                    "principal_id": row["principal_id"],
                    "tenant_id": row["tenant_id"],
                    "operation": row["operation"],
                    "resource": row["resource"],
                    "requested_effects": json.loads(row["requested_effects_json"]),
                    "decision": row["decision"],
                    "reason_code": row["reason_code"],
                }
                for row in rows
            ]
        finally:
            connection.close()
