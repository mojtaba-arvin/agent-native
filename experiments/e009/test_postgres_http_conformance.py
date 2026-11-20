"""Run the unchanged T04 black-box HTTP cases against PostgreSQL storage."""

from __future__ import annotations

import os
import threading
import unittest
import uuid

from audit import SQLiteAuditSink
from catalog import build_catalog_handlers
from http_server import create_server
from identity import MemoryIdentityProvider
from kernel import ServiceRuntime, load_service_ir
from repository import SQLiteCatalogRepository
from security_model import Grant, RequestContext

from test_http_conformance import (
    HTTPConformanceTests,
    RESTRICTED_TOKEN,
    SOURCE,
    TOKEN_A,
    TOKEN_B,
    TRUSTED_EFFECTS,
    make_context,
)
from test_postgres_storage import PostgresAuditSink, PostgresCatalogRepository


class PostgresHTTPConformanceTests(HTTPConformanceTests):
    """The same 14 HTTP-level assertions, with no SQLite in the request path."""

    def setUp(self) -> None:
        self.dsn = (
            os.environ.get("AGENT_NATIVE_E009_POSTGRES_DSN")
            or os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN")
        )
        if not self.dsn:
            self.skipTest("requires the PostgreSQL 16.4 service and psycopg")
        try:
            import psycopg  # noqa: F401
        except ImportError:
            self.skipTest("requires psycopg 3")

        self.schema = f"e009_t06_{uuid.uuid4().hex}"
        self.repository = PostgresCatalogRepository(self.dsn, schema=self.schema)
        self.audit_sink = PostgresAuditSink(self.dsn, schema=self.schema)
        self.work_store = None
        self.runtime = ServiceRuntime(
            load_service_ir(SOURCE),
            handlers=build_catalog_handlers(self.repository, self.work_store),
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: 100,
            audit_sink=self.audit_sink,
        )
        self.identity = MemoryIdentityProvider(
            {
                TOKEN_A: make_context("user-a", "tenant-a"),
                TOKEN_B: make_context("user-b", "tenant-b"),
                RESTRICTED_TOKEN: make_context(
                    "restricted-user", "tenant-a", grants=False
                ),
            }
        )
        self.server = create_server(self.runtime, self.identity, max_concurrency=8)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(timeout=5)
        if hasattr(self, "repository"):
            self.repository.close()
        if hasattr(self, "schema"):
            import psycopg
            from psycopg import sql

            with psycopg.connect(self.dsn) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(self.schema)
                    )
                )
