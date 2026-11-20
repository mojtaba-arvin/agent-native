"""PostgreSQL resource adapter for the production IR runtime.

The adapter deliberately supports only the frozen catalog and inventory
resource shapes. SQL identifiers are selected from an allowlist; request data
is always passed as bound parameters.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, Mapping


_SCHEMA = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_RESOURCES = {
    "items": {
        "key": "id",
        "columns": ("id", "name"),
        "types": {"name": str},
    },
    "stock": {
        "key": "sku",
        "columns": ("sku", "quantity", "warehouse_id"),
        "types": {"sku": str, "quantity": int, "warehouse_id": str},
    },
}


class PostgresResourceRepository:
    """Tenant-scoped PostgreSQL storage for the catalog and inventory IRs."""

    def __init__(self, dsn: str, *, schema: str = "agent_native"):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("postgres_dsn_required")
        if not isinstance(schema, str) or not _SCHEMA.fullmatch(schema):
            raise ValueError("invalid_postgres_schema")
        self.dsn = dsn
        self.schema = schema
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
        connection = psycopg.connect(self.dsn, row_factory=dict_row)
        connection.execute("SET synchronous_commit TO on")
        connection.execute("SET statement_timeout TO '10s'")
        return connection

    def _qualified(self, table: str):
        _psycopg, sql, _row = self._driver()
        return sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier(table))

    def _initialize(self) -> None:
        _psycopg, sql, _row = self._driver()
        with self._connect() as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema))
            )
            connection.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    tenant_id TEXT NOT NULL,
                    id UUID NOT NULL,
                    name TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, id),
                    UNIQUE (tenant_id, name)
                )
            """).format(self._qualified("items")))
            connection.execute(sql.SQL("""
                CREATE TABLE IF NOT EXISTS {} (
                    tenant_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity BIGINT NOT NULL CHECK (quantity >= 0),
                    warehouse_id TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, sku)
                )
            """).format(self._qualified("stock")))
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
                CREATE INDEX IF NOT EXISTS items_tenant_name_idx
                ON {} (tenant_id, name)
            """).format(self._qualified("items")))

    def _resource(self, resource: str) -> dict:
        if resource not in _RESOURCES:
            raise ValueError("unsupported_resource")
        return _RESOURCES[resource]

    def _row(self, resource: str, row: Mapping[str, Any] | None):
        if row is None:
            return None
        if resource == "items":
            return {"id": str(row["id"]), "name": row["name"]}
        return {
            "sku": row["sku"],
            "quantity": int(row["quantity"]),
            "warehouse_id": row["warehouse_id"],
        }

    def read(self, resource: str, key: Any, *, tenant_id: str):
        spec = self._resource(resource)
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id_required")
        with self._connect() as connection:
            row = connection.execute(
                self._select(resource) + " WHERE tenant_id = %s AND "
                + spec["key"] + " = %s",
                (tenant_id, key),
            ).fetchone()
        return self._row(resource, row)

    def read_by_field(self, resource: str, field: str, value: Any, *, tenant_id: str):
        spec = self._resource(resource)
        if field not in spec["columns"]:
            raise ValueError("unsupported_resource_field")
        with self._connect() as connection:
            row = connection.execute(
                self._select(resource) + " WHERE tenant_id = %s AND "
                + field + " = %s",
                (tenant_id, value),
            ).fetchone()
        return self._row(resource, row)

    def list(self, resource: str, filters: Mapping[str, Any], *, tenant_id: str):
        spec = self._resource(resource)
        if not isinstance(filters, Mapping) or not set(filters).issubset(set(spec["columns"])):
            raise ValueError("unsupported_resource_filter")
        where = ["tenant_id = %s"]
        values = [tenant_id]
        for field in sorted(filters):
            where.append(field + " = %s")
            values.append(filters[field])
        with self._connect() as connection:
            rows = connection.execute(
                self._select(resource) + " WHERE " + " AND ".join(where)
                + " ORDER BY " + spec["key"],
                values,
            ).fetchall()
        return [self._row(resource, row) for row in rows]

    @staticmethod
    def _select(resource: str) -> str:
        if resource == "items":
            return "SELECT id, name FROM items"
        if resource == "stock":
            return "SELECT sku, quantity, warehouse_id FROM stock"
        raise ValueError("unsupported_resource")

    def create(
        self, resource: str, payload: Mapping[str, Any], *,
        tenant_id: str, idempotency_key: str | None = None,
    ):
        spec = self._resource(resource)
        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("tenant_id_required")
        if not isinstance(payload, Mapping):
            raise ValueError("payload_must_be_object")
        expected = set(spec["columns"]) - {spec["key"]}
        if set(payload) != expected:
            raise ValueError("resource_payload_fields_mismatch")
        for name, expected_type in spec["types"].items():
            if name in payload and (type(payload[name]) is not expected_type):
                raise ValueError("invalid_resource_field:" + name)
        if resource == "stock" and payload["quantity"] < 0:
            raise ValueError("invalid_resource_field:quantity")

        canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = spec["key"]
        if resource == "items":
            result = {"id": str(uuid.uuid4()), "name": payload["name"]}
        else:
            result = dict(payload)

        with self._connect() as connection:
            with connection.transaction():
                if idempotency_key is not None:
                    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
                        raise ValueError("invalid_idempotency_key")
                    lock = json.dumps([tenant_id, resource, idempotency_key], separators=(",", ":"))
                    connection.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock,)
                    )
                    previous = connection.execute(
                        "SELECT request_sha256, response_json FROM "
                        + self.schema + ".idempotency_keys "
                        "WHERE tenant_id = %s AND resource = %s AND idempotency_key = %s",
                        (tenant_id, resource, idempotency_key),
                    ).fetchone()
                    if previous:
                        if previous["request_sha256"] != digest:
                            raise ValueError("idempotency_key_reused_with_different_request")
                        return previous["response_json"]
                if resource == "items":
                    connection.execute(
                        "INSERT INTO " + self.schema + ".items (tenant_id, id, name) VALUES (%s, %s, %s)",
                        (tenant_id, result["id"], result["name"]),
                    )
                else:
                    connection.execute(
                        "INSERT INTO " + self.schema + ".stock (tenant_id, sku, quantity, warehouse_id) VALUES (%s, %s, %s, %s)",
                        (tenant_id, result["sku"], result["quantity"], result["warehouse_id"]),
                    )
                if idempotency_key is not None:
                    connection.execute(
                        "INSERT INTO " + self.schema + ".idempotency_keys "
                        "(tenant_id, resource, idempotency_key, request_sha256, response_json) "
                        "VALUES (%s, %s, %s, %s, %s::jsonb)",
                        (tenant_id, resource, idempotency_key, digest, json.dumps(result)),
                    )
        return result

    def update(self, resource: str, key_value: Any, payload: Mapping[str, Any], *, tenant_id: str):
        spec = self._resource(resource)
        allowed = set(spec["columns"]) - {spec["key"]}
        if not isinstance(payload, Mapping) or not payload or not set(payload).issubset(allowed):
            raise ValueError("resource_update_fields_mismatch")
        for name, value in payload.items():
            if type(value) is not spec["types"][name]:
                raise ValueError("invalid_resource_field:" + name)
        if resource == "stock" and payload.get("quantity", 0) < 0:
            raise ValueError("invalid_resource_field:quantity")
        assignments = ", ".join(field + " = %s" for field in sorted(payload))
        values = [payload[field] for field in sorted(payload)]
        values.extend([tenant_id, key_value])
        with self._connect() as connection:
            row = connection.execute(
                "UPDATE " + resource + " SET " + assignments
                + " WHERE tenant_id = %s AND " + spec["key"] + " = %s RETURNING *",
                values,
            ).fetchone()
        return self._row(resource, row)

    def delete(self, resource: str, key_value: Any, *, tenant_id: str) -> bool:
        spec = self._resource(resource)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM " + resource + " WHERE tenant_id = %s AND "
                + spec["key"] + " = %s",
                (tenant_id, key_value),
            )
            return cursor.rowcount == 1

    def close(self) -> None:
        """Connections are scoped to individual operations."""
