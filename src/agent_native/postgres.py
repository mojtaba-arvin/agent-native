"""Tenant-scoped PostgreSQL storage with IR migrations and atomic write events."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Mapping

from .migrations import IRMigrationPlanner, MigrationError, ResourceSpec
from .runtime import DomainFault


_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RESOURCE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PostgresResourceRepository:
    """PostgreSQL adapter; resource schema is installed from validated service IR."""

    def __init__(self, dsn: str, *, schema: str = "agent_native", _fault_hook=None):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("postgres_dsn_required")
        if not isinstance(schema, str) or not _SCHEMA.fullmatch(schema):
            raise ValueError("invalid_postgres_schema")
        self.dsn = dsn
        self.schema = schema
        self._fault_hook = _fault_hook
        self._resources: dict[str, ResourceSpec] = {}
        self._initialize()

    @staticmethod
    def _driver():
        try:
            import psycopg
            from psycopg import sql
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("PostgreSQL runtime requires psycopg 3") from error
        return psycopg, sql, dict_row

    def _connect(self):
        psycopg, _sql, dict_row = self._driver()
        connection = psycopg.connect(
            self.dsn, row_factory=dict_row, options=f"-c search_path={self.schema}"
        )
        connection.execute("SET synchronous_commit TO on")
        connection.execute("SET statement_timeout TO '10s'")
        return connection

    def _qualified(self, table: str):
        _psycopg, sql, _row = self._driver()
        if not _RESOURCE.fullmatch(table):
            raise ValueError("invalid_sql_identifier")
        return sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier(table))

    def _initialize(self) -> None:
        _psycopg, sql, _row = self._driver()
        with self._connect() as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema))
            )
            connection.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    service_id TEXT NOT NULL,
                    service_version TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (service_id, service_version)
                )
            """).format(self._qualified("schema_migrations")))
            connection.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    tenant_id TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    response_json JSONB NOT NULL,
                    PRIMARY KEY (tenant_id, resource, idempotency_key)
                )
            """).format(self._qualified("idempotency_keys")))
            connection.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    sequence BIGSERIAL PRIMARY KEY,
                    event_id UUID NOT NULL UNIQUE,
                    request_id TEXT NOT NULL,
                    principal_id TEXT,
                    tenant_id TEXT,
                    operation TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
                    reason_code TEXT NOT NULL,
                    event_json JSONB NOT NULL,
                    created_at BIGINT NOT NULL
                )
            """).format(self._qualified("audit_log")))
            connection.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    event_id UUID PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    payload_json JSONB NOT NULL,
                    created_at BIGINT NOT NULL,
                    lease_owner TEXT,
                    lease_token BIGINT NOT NULL DEFAULT 0,
                    lease_until BIGINT,
                    delivered_at BIGINT
                )
            """).format(self._qualified("outbox")))
            connection.execute("""
                CREATE OR REPLACE FUNCTION agent_native_reject_audit_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'audit_append_only'; END;
                $$
            """)
            for trigger, action, level in (
                ("audit_no_update", "UPDATE", "FOR EACH ROW"),
                ("audit_no_delete", "DELETE", "FOR EACH ROW"),
                ("audit_no_truncate", "TRUNCATE", "FOR EACH STATEMENT"),
            ):
                connection.execute(
                    sql.SQL("DROP TRIGGER IF EXISTS {} ON {}").format(
                        sql.Identifier(trigger), self._qualified("audit_log")
                    )
                )
                connection.execute(
                    sql.SQL("CREATE TRIGGER {} BEFORE {} ON {} {} "
                            "EXECUTE FUNCTION agent_native_reject_audit_mutation()").format(
                        sql.Identifier(trigger), sql.SQL(action),
                        self._qualified("audit_log"), sql.SQL(level)
                    )
                )

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def migrate_service(self, service: Any) -> bool:
        plan = IRMigrationPlanner.from_service(service)
        psycopg, _sql, _row = self._driver()
        with self._connect() as connection:
            with connection.transaction():
                lock_key = f"{self.schema}:{plan.service_id}"
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,)
                )
                existing = connection.execute(
                    "SELECT checksum FROM " + self.schema +
                    ".schema_migrations WHERE service_id=%s AND service_version=%s",
                    (plan.service_id, plan.service_version),
                ).fetchone()
                if existing and existing["checksum"] != plan.checksum:
                    raise MigrationError("migration_checksum_changed_for_published_version")
                for resource in plan.resources:
                    self._create_resource_table(connection, resource)
                if existing is None:
                    connection.execute(
                        "INSERT INTO " + self.schema +
                        ".schema_migrations(service_id,service_version,checksum) VALUES(%s,%s,%s)",
                        (plan.service_id, plan.service_version, plan.checksum),
                    )
        for resource in plan.resources:
            previous = self._resources.get(resource.name)
            if previous is not None and previous != resource:
                raise MigrationError("resource_schema_conflict:" + resource.name)
            self._resources[resource.name] = resource
        return existing is None

    def migrate_services(self, services) -> tuple[bool, ...]:
        results = []
        for service in services:
            results.append(self.migrate_service(service))
        return tuple(results)

    def _create_resource_table(self, connection, resource: ResourceSpec) -> None:
        _psycopg, sql, _row = self._driver()
        definitions = ["tenant_id TEXT NOT NULL"]
        for column in resource.columns:
            default = " DEFAULT gen_random_uuid()" if column.name == resource.key and resource.generated_key and column.sql_type == "UUID" else ""
            definitions.append(
                sql.Identifier(column.name).as_string(connection) + " " + column.sql_type + " NOT NULL" + default
            )
        definitions.append(
            "PRIMARY KEY (tenant_id, " + sql.Identifier(resource.key).as_string(connection) + ")"
        )
        for field in resource.unique_fields:
            definitions.append(
                "UNIQUE (tenant_id, " + sql.Identifier(field).as_string(connection) + ")"
            )
        statement = (
            "CREATE TABLE IF NOT EXISTS "
            + self._qualified(resource.name).as_string(connection)
            + " (" + ", ".join(definitions) + ")"
        )
        connection.execute(statement)

    def migration_history(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT service_id,service_version,checksum FROM " + self.schema +
                ".schema_migrations ORDER BY service_id,service_version"
            ).fetchall()
        return [dict(row) for row in rows]

    def resource_schema(self, resource: str) -> ResourceSpec:
        return self._resource(resource)

    def _resource(self, resource: str) -> ResourceSpec:
        spec = self._resources.get(resource) if isinstance(resource, str) else None
        if spec is None:
            raise ValueError("unsupported_resource")
        return spec

    @staticmethod
    def _canonical(value: Mapping[str, Any]) -> str:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    def _row(self, resource: str, row: Mapping[str, Any] | None):
        if row is None:
            return None
        spec = self._resource(resource)
        result = {}
        for column in spec.columns:
            value = row[column.name]
            result[column.name] = str(value) if column.sql_type == "UUID" and value is not None else value
        return result

    def _select(self, resource: str) -> str:
        spec = self._resource(resource)
        columns = ", ".join(column.name for column in spec.columns)
        return "SELECT " + columns + " FROM " + self.schema + "." + resource

    def read(self, resource: str, key: Any, *, tenant_id: str):
        spec = self._resource(resource)
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id_required")
        with self._connect() as connection:
            row = connection.execute(
                self._select(resource) + " WHERE tenant_id = %s AND " + spec.key + " = %s",
                (tenant_id, key),
            ).fetchone()
        return self._row(resource, row)

    def read_by_field(self, resource: str, field: str, value: Any, *, tenant_id: str):
        spec = self._resource(resource)
        if field not in {column.name for column in spec.columns}:
            raise ValueError("unsupported_resource_field")
        with self._connect() as connection:
            row = connection.execute(
                self._select(resource) + " WHERE tenant_id = %s AND " + field + " = %s",
                (tenant_id, value),
            ).fetchone()
        return self._row(resource, row)

    def list(self, resource: str, filters: Mapping[str, Any], *, tenant_id: str):
        spec = self._resource(resource)
        allowed = {column.name for column in spec.columns}
        if not isinstance(filters, Mapping) or not set(filters).issubset(allowed):
            raise ValueError("unsupported_resource_filter")
        where = ["tenant_id = %s"]
        values = [tenant_id]
        for field in sorted(filters):
            where.append(field + " = %s")
            values.append(filters[field])
        with self._connect() as connection:
            rows = connection.execute(
                self._select(resource) + " WHERE " + " AND ".join(where) + " ORDER BY " + spec.key,
                values,
            ).fetchall()
        return [self._row(resource, row) for row in rows]

    def write_in_transaction(self, connection, audit_event: Mapping[str, Any]) -> None:
        """Insert an audit event using the caller's active write transaction."""
        if not isinstance(audit_event, Mapping):
            raise ValueError("audit_event_must_be_object")
        request_id = audit_event.get("request_id")
        operation = audit_event.get("operation")
        decision = audit_event.get("decision")
        reason = audit_event.get("reason_code")
        if not all(isinstance(value, str) and value for value in (request_id, operation, decision, reason)):
            raise ValueError("invalid_audit_event")
        if decision not in {"allow", "deny"}:
            raise ValueError("invalid_audit_decision")
        canonical = self._canonical(audit_event)
        connection.execute(
            "INSERT INTO " + self.schema +
            ".audit_log(event_id,request_id,principal_id,tenant_id,operation,resource,decision,reason_code,event_json,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (
                str(uuid.uuid4()), request_id, audit_event.get("principal_id"),
                audit_event.get("tenant_id"), operation, audit_event.get("resource", ""),
                decision, reason, canonical, int(audit_event.get("timestamp", 0)),
            ),
        )

    def _write_outbox(self, connection, *, tenant_id: str, request_id: str,
                      event_type: str, payload: Mapping[str, Any], created_at: int) -> str:
        if not isinstance(event_type, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,95}", event_type):
            raise ValueError("invalid_outbox_event_type")
        event_id = str(uuid.uuid4())
        connection.execute(
            "INSERT INTO " + self.schema +
            ".outbox(event_id,tenant_id,event_type,request_id,payload_json,created_at) "
            "VALUES(%s,%s,%s,%s,%s::jsonb,%s)",
            (event_id, tenant_id, event_type, request_id,
             self._canonical(payload), created_at),
        )
        return event_id

    def __call__(self, audit_event: Mapping[str, Any]) -> None:
        with self._connect() as connection:
            with connection.transaction():
                self.write_in_transaction(connection, audit_event)

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                table: int(connection.execute(
                    "SELECT COUNT(*) AS count FROM " + self.schema + "." + table
                ).fetchone()["count"])
                for table in ("audit_log", "outbox", "idempotency_keys")
            }

    def outbox_events(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT event_id,tenant_id,event_type,request_id,payload_json,created_at FROM " + self.schema + ".outbox"
        params = ()
        if tenant_id is not None:
            query += " WHERE tenant_id=%s"
            params = (tenant_id,)
        query += " ORDER BY created_at,event_id"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def audit_events(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT event_id,request_id,principal_id,tenant_id,operation,resource,decision,reason_code,event_json,created_at FROM " + self.schema + ".audit_log"
        params = ()
        if tenant_id is not None:
            query += " WHERE tenant_id=%s"
            params = (tenant_id,)
        query += " ORDER BY sequence"
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def _commit_write(self, connection, *, resource: str, operation: str,
                      tenant_id: str, result: Mapping[str, Any],
                      audit_event: Mapping[str, Any] | None,
                      audit_receipt: Any = None) -> None:
        if audit_event is None:
            return
        self._fault("after_data")
        self.write_in_transaction(connection, audit_event)
        self._fault("after_audit")
        self._write_outbox(
            connection, tenant_id=tenant_id,
            request_id=str(audit_event["request_id"]),
            event_type=f"{resource}.{operation}",
            payload={"resource": resource, "operation": operation, "data": dict(result)},
            created_at=int(audit_event.get("timestamp", 0)),
        )
        self._fault("after_outbox")

    def create(
        self, resource: str, payload: Mapping[str, Any], *,
        tenant_id: str, idempotency_key: str | None = None,
        audit_event: Mapping[str, Any] | None = None, audit_receipt: Any = None,
    ):
        spec = self._resource(resource)
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(payload, Mapping) or set(payload) != set(spec.create_fields):
            raise ValueError("resource_payload_fields_mismatch")
        for column in spec.columns:
            if column.name not in payload:
                continue
            value = payload[column.name]
            if column.sql_type == "BIGINT" and type(value) is not int:
                raise ValueError("invalid_resource_field:" + column.name)
            if column.sql_type == "BOOLEAN" and type(value) is not bool:
                raise ValueError("invalid_resource_field:" + column.name)
            if column.sql_type == "DOUBLE PRECISION" and (
                type(value) not in {int, float} or isinstance(value, bool)
            ):
                raise ValueError("invalid_resource_field:" + column.name)
            if column.sql_type not in {"BIGINT", "BOOLEAN", "DOUBLE PRECISION"} and not isinstance(value, column.python_type):
                raise ValueError("invalid_resource_field:" + column.name)
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not idempotency_key.strip()
        ):
            raise ValueError("invalid_idempotency_key")
        digest = hashlib.sha256(self._canonical(payload).encode("utf-8")).hexdigest()
        result = dict(payload)
        if spec.generated_key:
            result[spec.key] = str(uuid.uuid4())

        psycopg, _sql, _row = self._driver()
        try:
            with self._connect() as connection:
                with connection.transaction():
                    previous = None
                    if idempotency_key is not None:
                        lock = json.dumps([tenant_id, resource, idempotency_key], separators=(",", ":"))
                        connection.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock,)
                        )
                        previous = connection.execute(
                            "SELECT request_sha256,response_json FROM " + self.schema +
                            ".idempotency_keys WHERE tenant_id=%s AND resource=%s AND idempotency_key=%s",
                            (tenant_id, resource, idempotency_key),
                        ).fetchone()
                    if previous is not None:
                        if previous["request_sha256"] != digest:
                            raise DomainFault("Conflict", "idempotency_key_reused_with_different_request")
                        result = previous["response_json"]
                        if audit_event is not None:
                            self.write_in_transaction(connection, audit_event)
                    else:
                        columns = ["tenant_id"] + [column.name for column in spec.columns]
                        values = [tenant_id] + [result[column.name] for column in spec.columns]
                        connection.execute(
                            "INSERT INTO " + self.schema + "." + resource +
                            " (" + ", ".join(columns) + ") VALUES (" +
                            ", ".join(["%s"] * len(columns)) + ")",
                            values,
                        )
                        if idempotency_key is not None:
                            connection.execute(
                                "INSERT INTO " + self.schema +
                                ".idempotency_keys(tenant_id,resource,idempotency_key,request_sha256,response_json) "
                                "VALUES(%s,%s,%s,%s,%s::jsonb)",
                                (tenant_id, resource, idempotency_key, digest, self._canonical(result)),
                            )
                        self._commit_write(
                            connection, resource=resource, operation="created",
                            tenant_id=tenant_id, result=result, audit_event=audit_event,
                        )
            if audit_event is not None and audit_receipt is not None:
                audit_receipt.mark_committed()
            self._fault("after_commit")
            return result
        except psycopg.errors.UniqueViolation as error:
            if audit_event is not None and audit_receipt is not None:
                audit_receipt.mark_failed()
            raise DomainFault("Conflict", "resource_conflict") from error
        except Exception:
            if audit_event is not None and audit_receipt is not None and not audit_receipt.committed:
                audit_receipt.mark_failed()
            raise


    def update(
        self, resource: str, key_value: Any, payload: Mapping[str, Any], *,
        tenant_id: str, audit_event: Mapping[str, Any] | None = None,
        audit_receipt: Any = None,
    ):
        spec = self._resource(resource)
        allowed = {column.name for column in spec.columns} - {spec.key}
        if not isinstance(payload, Mapping) or not payload or not set(payload).issubset(allowed):
            raise ValueError("resource_update_fields_mismatch")
        for column in spec.columns:
            if column.name in payload:
                value = payload[column.name]
                if column.sql_type == "BIGINT" and type(value) is not int:
                    raise ValueError("invalid_resource_field:" + column.name)
                if column.sql_type == "BOOLEAN" and type(value) is not bool:
                    raise ValueError("invalid_resource_field:" + column.name)
                if column.sql_type not in {"BIGINT", "BOOLEAN", "DOUBLE PRECISION"} and not isinstance(value, column.python_type):
                    raise ValueError("invalid_resource_field:" + column.name)
        assignments = ", ".join(field + " = %s" for field in sorted(payload))
        values = [payload[field] for field in sorted(payload)] + [tenant_id, key_value]
        try:
            with self._connect() as connection:
                with connection.transaction():
                    row = connection.execute(
                        "UPDATE " + self.schema + "." + resource + " SET " + assignments +
                        " WHERE tenant_id=%s AND " + spec.key + "=%s RETURNING *", values
                    ).fetchone()
                    result = self._row(resource, row)
                    if result is not None:
                        self._commit_write(
                            connection, resource=resource, operation="updated",
                            tenant_id=tenant_id, result=result, audit_event=audit_event,
                        )
            if result is not None and audit_event is not None and audit_receipt is not None:
                audit_receipt.mark_committed()
            self._fault("after_commit")
            return result
        except Exception:
            if audit_event is not None and audit_receipt is not None and not audit_receipt.committed:
                audit_receipt.mark_failed()
            raise


    def delete(
        self, resource: str, key_value: Any, *, tenant_id: str,
        audit_event: Mapping[str, Any] | None = None, audit_receipt: Any = None,
    ) -> bool:
        spec = self._resource(resource)
        try:
            with self._connect() as connection:
                with connection.transaction():
                    row = connection.execute(
                        "DELETE FROM " + self.schema + "." + resource +
                        " WHERE tenant_id=%s AND " + spec.key + "=%s RETURNING *",
                        (tenant_id, key_value),
                    ).fetchone()
                    result = self._row(resource, row)
                    if result is not None:
                        self._commit_write(
                            connection, resource=resource, operation="deleted",
                            tenant_id=tenant_id, result=result, audit_event=audit_event,
                        )
            if result is not None and audit_event is not None and audit_receipt is not None:
                audit_receipt.mark_committed()
            self._fault("after_commit")
            return result is not None
        except Exception:
            if audit_event is not None and audit_receipt is not None and not audit_receipt.committed:
                audit_receipt.mark_failed()
            raise


    def publish(
        self, event_type: str, payload: Mapping[str, Any], *,
        tenant_id: str, request_id: str,
        audit_event: Mapping[str, Any] | None = None,
        audit_receipt: Any = None,
    ):
        if not isinstance(payload, Mapping):
            raise ValueError("event_payload_must_be_object")
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id_required")
        event_id = None
        try:
            with self._connect() as connection:
                with connection.transaction():
                    if audit_event is not None:
                        self.write_in_transaction(connection, audit_event)
                    event_id = self._write_outbox(
                        connection, tenant_id=tenant_id, request_id=request_id,
                        event_type=event_type, payload=payload,
                        created_at=int(audit_event.get("timestamp", 0)) if audit_event else 0,
                    )
            if audit_event is not None and audit_receipt is not None:
                audit_receipt.mark_committed()
            self._fault("after_commit")
            return {"id": event_id, "state": "queued"}
        except Exception:
            if audit_event is not None and audit_receipt is not None and not audit_receipt.committed:
                audit_receipt.mark_failed()
            raise


    def close(self) -> None:
        """Connections are scoped to individual operations."""
