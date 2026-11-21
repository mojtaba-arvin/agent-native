"""PostgreSQL storage fixtures for the E-009 HTTP reference conformance suite.

These adapters deliberately implement the same small surface consumed by the
E-009 catalog handlers. They are conformance fixtures, not a product database
selection or a replacement for the independent E-002 durability experiment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Any

from repository import IdempotencyConflict, ItemConflict


_SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_AUDIT_FIELDS = {
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


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")
    return value


def _driver():
    try:
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL E-009 conformance requires psycopg 3"
        ) from error
    return psycopg, sql, dict_row


class _PostgresE009Storage:
    def __init__(self, dsn: str | None, schema: str):
        self.dsn = (
            dsn
            or os.environ.get("AGENT_NATIVE_E009_POSTGRES_DSN")
            or os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN")
        )
        if not self.dsn:
            raise ValueError("postgres_dsn_required")
        if not isinstance(schema, str) or not _SCHEMA_RE.fullmatch(schema):
            raise ValueError("invalid_postgres_schema")
        self.schema = schema

        psycopg, sql, _dict_row = _driver()
        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(self.schema)
                )
            )

    def _connect(self):
        psycopg, _sql, dict_row = _driver()
        connection = psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            options=f"-c search_path={self.schema}",
        )
        connection.execute("SET synchronous_commit TO on")
        connection.execute("SET statement_timeout TO '10s'")
        return connection

    def close(self) -> None:
        """Connections are operation-scoped; retained for lifecycle symmetry."""


class PostgresCatalogRepository(_PostgresE009Storage):
    """Tenant-scoped item and idempotency repository on PostgreSQL."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        schema: str = "agent_native_e009",
    ):
        super().__init__(dsn, schema)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS e009_items (
                    tenant_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    PRIMARY KEY (tenant_id, id),
                    UNIQUE (tenant_id, name)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS e009_idempotency_keys (
                    tenant_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    PRIMARY KEY (tenant_id, idempotency_key)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS e009_items_tenant_name_idx
                ON e009_items(tenant_id, name)
                """
            )

    @staticmethod
    def _item(row: dict[str, Any] | None) -> dict[str, str] | None:
        if row is None:
            return None
        return {"id": str(row["id"]), "name": str(row["name"])}

    def create_item(
        self,
        *,
        tenant_id: str,
        name: str,
        idempotency_key: str,
        now: int,
    ) -> tuple[dict[str, str], bool]:
        tenant_id = _required_text(tenant_id, "tenant_id")
        name = _required_text(name, "item_name")
        idempotency_key = _required_text(idempotency_key, "idempotency_key")
        if type(now) is not int or now < 0:
            raise ValueError("invalid_trusted_time")

        request_sha256 = hashlib.sha256(
            _canonical_json({"name": name}).encode("utf-8")
        ).hexdigest()
        lock_key = _canonical_json([tenant_id, idempotency_key])

        try:
            with self._connect() as connection:
                # SQLite's BEGIN IMMEDIATE serialized writers. Use a
                # transaction-scoped lock for the corresponding PostgreSQL
                # idempotency scope, including the not-yet-existing row case.
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_key,),
                )
                previous = connection.execute(
                    """
                    SELECT request_sha256, response_json
                    FROM e009_idempotency_keys
                    WHERE tenant_id = %s AND idempotency_key = %s
                    """,
                    (tenant_id, idempotency_key),
                ).fetchone()
                if previous is not None:
                    if previous["request_sha256"] != request_sha256:
                        raise IdempotencyConflict(
                            "idempotency_key_reused_with_different_request"
                        )
                    return json.loads(previous["response_json"]), True

                item = {"id": str(uuid.uuid4()), "name": name}
                connection.execute(
                    """
                    INSERT INTO e009_items(tenant_id, id, name, created_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (tenant_id, item["id"], item["name"], now),
                )
                connection.execute(
                    """
                    INSERT INTO e009_idempotency_keys(
                        tenant_id, idempotency_key, request_sha256,
                        response_json, created_at
                    ) VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        tenant_id,
                        idempotency_key,
                        request_sha256,
                        _canonical_json(item),
                        now,
                    ),
                )
                return item, False
        except Exception as error:
            if getattr(error, "sqlstate", None) == "23505":
                constraint = getattr(
                    getattr(error, "diag", None), "constraint_name", None
                )
                if constraint == "e009_items_tenant_id_name_key":
                    raise ItemConflict(
                        "item_name_already_exists_for_tenant"
                    ) from error
            raise

    def get_item(self, *, tenant_id: str, item_id: str) -> dict[str, str] | None:
        tenant_id = _required_text(tenant_id, "tenant_id")
        item_id = _required_text(item_id, "item_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name FROM e009_items
                WHERE tenant_id = %s AND id = %s
                """,
                (tenant_id, item_id),
            ).fetchone()
            return self._item(row)

    def get_item_by_name(
        self, *, tenant_id: str, name: str
    ) -> dict[str, str] | None:
        tenant_id = _required_text(tenant_id, "tenant_id")
        name = _required_text(name, "item_name")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name FROM e009_items
                WHERE tenant_id = %s AND name = %s
                """,
                (tenant_id, name),
            ).fetchone()
            return self._item(row)

    def list_items(self, *, tenant_id: str) -> list[dict[str, str]]:
        tenant_id = _required_text(tenant_id, "tenant_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name FROM e009_items
                WHERE tenant_id = %s
                ORDER BY created_at, id
                """,
                (tenant_id,),
            ).fetchall()
            return [self._item(row) for row in rows]


class PostgresAuditSink(_PostgresE009Storage):
    """Synchronous, append-only audit sink using PostgreSQL durable commits."""

    def __init__(
        self,
        dsn: str | None = None,
        *,
        schema: str = "agent_native_e009",
    ):
        super().__init__(dsn, schema)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS e009_audit_events (
                    event_id BIGSERIAL PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    timestamp BIGINT NOT NULL CHECK (timestamp >= 0),
                    principal_id TEXT,
                    tenant_id TEXT,
                    operation TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    requested_effects_json TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
                    reason_code TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS e009_audit_events_request_idx
                ON e009_audit_events(request_id, event_id)
                """
            )
            connection.execute(
                """
                CREATE OR REPLACE FUNCTION e009_reject_audit_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'audit_events_are_append_only';
                END;
                $$
                """
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS e009_audit_no_update ON e009_audit_events"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS e009_audit_no_delete ON e009_audit_events"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS e009_audit_no_truncate ON e009_audit_events"
            )
            connection.execute(
                """
                CREATE TRIGGER e009_audit_no_update
                BEFORE UPDATE ON e009_audit_events
                FOR EACH ROW EXECUTE FUNCTION e009_reject_audit_mutation()
                """
            )
            connection.execute(
                """
                CREATE TRIGGER e009_audit_no_delete
                BEFORE DELETE ON e009_audit_events
                FOR EACH ROW EXECUTE FUNCTION e009_reject_audit_mutation()
                """
            )
            connection.execute(
                """
                CREATE TRIGGER e009_audit_no_truncate
                BEFORE TRUNCATE ON e009_audit_events
                FOR EACH STATEMENT EXECUTE FUNCTION e009_reject_audit_mutation()
                """
            )

    @staticmethod
    def _prepare(event: dict[str, Any]) -> tuple:
        if not isinstance(event, dict) or set(event) != _AUDIT_FIELDS:
            raise ValueError("invalid_audit_event_fields")

        for name in (
            "operation",
            "resource",
            "decision",
            "reason_code",
            "request_id",
        ):
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
            or any(
                not isinstance(item, str) or not item.strip()
                for item in effects
            )
        ):
            raise ValueError("invalid_audit_requested_effects")

        return (
            event["request_id"],
            event["timestamp"],
            event["principal_id"],
            event["tenant_id"],
            event["operation"],
            event["resource"],
            json.dumps(
                sorted(set(effects)),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            event["decision"],
            event["reason_code"],
        )

    def write_in_transaction(self, connection: Any, event: dict[str, Any]) -> None:
        """Append through a caller-owned transaction in this schema."""
        connection.execute(
            """
            INSERT INTO e009_audit_events(
                request_id, timestamp, principal_id, tenant_id, operation,
                resource, requested_effects_json, decision, reason_code
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            self._prepare(event),
        )

    def note_transactional_commit(self) -> None:
        """Match the SQLite sink interface; PostgreSQL commit is synchronous."""

    def __call__(self, event: dict[str, Any]) -> None:
        try:
            with self._connect() as connection:
                self.write_in_transaction(connection, event)
        except Exception as error:
            raise OSError("audit_commit_failed") from error

    def list_events(
        self, *, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if request_id is None:
                rows = connection.execute(
                    "SELECT * FROM e009_audit_events ORDER BY event_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM e009_audit_events
                    WHERE request_id = %s ORDER BY event_id
                    """,
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
                    "requested_effects": json.loads(
                        row["requested_effects_json"]
                    ),
                    "decision": row["decision"],
                    "reason_code": row["reason_code"],
                }
                for row in rows
            ]
