"""Tenant-scoped SQLite repository for the E-009 kernel vertical slice.

SQLite is used here as a local transactional reference substrate, not a
production persistence decision. Every read/write requires a trusted tenant
identifier. Item state and idempotency records commit in one transaction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class RepositoryError(RuntimeError):
    pass


class ItemNotFound(RepositoryError):
    pass


class ItemConflict(RepositoryError):
    pass


class IdempotencyConflict(RepositoryError):
    pass


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class SQLiteCatalogRepository:
    """A durable, tenant-isolated repository with atomic idempotent creation."""

    def __init__(self, database: str | Path):
        raw = str(database)
        if raw != ":memory:":
            path = Path(raw).expanduser().resolve()
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.database = str(path)
        else:
            self.database = raw
        self._initialize()

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

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RepositoryError("database_schema_is_newer_than_runtime")
            if version < 1:
                connection.execute(
                    """
                    CREATE TABLE items (
                        tenant_id TEXT NOT NULL,
                        id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY (tenant_id, id),
                        UNIQUE (tenant_id, name)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE idempotency_keys (
                        tenant_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        request_sha256 TEXT NOT NULL,
                        response_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY (tenant_id, idempotency_key)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX items_tenant_name_idx ON items(tenant_id, name)"
                )
                connection.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (1, 0)"
                )
                connection.execute("PRAGMA user_version = 1")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _item(row: sqlite3.Row | None) -> dict[str, str] | None:
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
        tenant_id = _require_text(tenant_id, "tenant_id")
        name = _require_text(name, "item_name")
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        if type(now) is not int or now < 0:
            raise ValueError("invalid_trusted_time")
        request_sha256 = hashlib.sha256(
            _canonical_json({"name": name}).encode("utf-8")
        ).hexdigest()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT request_sha256, response_json
                FROM idempotency_keys
                WHERE tenant_id = ? AND idempotency_key = ?
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if previous is not None:
                if previous["request_sha256"] != request_sha256:
                    raise IdempotencyConflict("idempotency_key_reused_with_different_request")
                result = json.loads(previous["response_json"])
                connection.commit()
                return result, True

            item = {"id": str(uuid.uuid4()), "name": name}
            connection.execute(
                """
                INSERT INTO items(tenant_id, id, name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (tenant_id, item["id"], item["name"], now),
            )
            connection.execute(
                """
                INSERT INTO idempotency_keys(
                    tenant_id, idempotency_key, request_sha256, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (tenant_id, idempotency_key, request_sha256, _canonical_json(item), now),
            )
            connection.commit()
            return item, False
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise ItemConflict("item_name_already_exists_for_tenant") from error
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_item(self, *, tenant_id: str, item_id: str) -> dict[str, str] | None:
        tenant_id = _require_text(tenant_id, "tenant_id")
        item_id = _require_text(item_id, "item_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id, name FROM items WHERE tenant_id = ? AND id = ?",
                (tenant_id, item_id),
            ).fetchone()
            return self._item(row)
        finally:
            connection.close()

    def get_item_by_name(self, *, tenant_id: str, name: str) -> dict[str, str] | None:
        tenant_id = _require_text(tenant_id, "tenant_id")
        name = _require_text(name, "item_name")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id, name FROM items WHERE tenant_id = ? AND name = ?",
                (tenant_id, name),
            ).fetchone()
            return self._item(row)
        finally:
            connection.close()

    def close(self) -> None:
        """Connections are scoped to operations; retained for lifecycle symmetry."""
        return None
