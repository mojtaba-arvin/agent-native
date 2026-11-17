"""Durable, append-only application audit sink for the E-009 SQLite reference kernel.

This is a single-node persistence component, not a tamper-proof remote audit service.
"""

from __future__ import annotations

import json
import sqlite3
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
    """Persist authorization decisions before the request handler is invoked."""

    def __init__(self, database: str | Path):
        raw = str(database)
        if raw == ":memory:":
            raise ValueError("file_backed_audit_database_required")
        self.database = str(Path(raw).expanduser().resolve())
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

    def __call__(self, event: dict[str, Any]) -> None:
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
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO audit_events(
                    request_id, timestamp, principal_id, tenant_id, operation,
                    resource, requested_effects_json, decision, reason_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["request_id"],
                    event["timestamp"],
                    event["principal_id"],
                    event["tenant_id"],
                    event["operation"],
                    event["resource"],
                    effects_json,
                    event["decision"],
                    event["reason_code"],
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
