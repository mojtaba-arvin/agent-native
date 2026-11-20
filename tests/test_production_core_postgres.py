from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from agent_native import (
    Grant,
    PostgresResourceRepository,
    RequestContext,
    RuntimeAdapters,
    ServiceHost,
    built_in_handler_registry,
)

ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN")


@unittest.skipUnless(DSN, "requires the Layer 1 disposable PostgreSQL service")
class ProductionCorePostgresTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = "t11_" + uuid.uuid4().hex[:20]
        self.repository = PostgresResourceRepository(DSN, schema=self.schema)
        self.handlers = built_in_handler_registry()
        self.host = ServiceHost(
            ROOT / "services",
            handlers=self.handlers,
            adapters=RuntimeAdapters(
                repository=self.repository,
                jobs=object(),
                events=self.repository,
            ),
            clock=lambda: 100,
            audit_sink=self.repository,
        )

    def tearDown(self) -> None:
        if hasattr(self, "repository"):
            _psycopg, sql, _row = self.repository._driver()
            with self.repository._connect() as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                        sql.Identifier(self.schema)
                    )
                )

    @staticmethod
    def _identity(tenant: str, capabilities: tuple[tuple[str, str], ...]) -> RequestContext:
        principal = "principal-" + tenant
        return RequestContext(
            principal_id=principal,
            tenant_id=tenant,
            now=100,
            grants=tuple(
                Grant(principal, tenant, capability, prefix)
                for capability, prefix in capabilities
            ),
        )

    def _catalog_identity(self, tenant: str = "tenant-a"):
        return self._identity(tenant, (
            ("items.read", "/items"),
            ("items.create", "/items"),
        ))

    def _inventory_identity(self, tenant: str = "tenant-a"):
        return self._identity(tenant, (
            ("stock.read", "/stock"),
            ("stock.write", "/stock"),
        ))

    def test_catalog_postgres_matches_reference_trace(self) -> None:
        identity = self._catalog_identity()
        trace = []

        created = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Desk lamp"}, identity,
            headers={"idempotency-key": "catalog-trace-001"},
        )
        self.assertEqual(created.status_code, 201)
        item = created.body["data"]
        trace.append(("create", created.status_code, item["name"]))

        replay = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Desk lamp"}, identity,
            headers={"idempotency-key": "catalog-trace-001"},
        )
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.body["data"], item)
        trace.append(("idempotent-replay", replay.status_code, replay.body["data"]["id"]))

        mismatched_replay = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Different lamp"}, identity,
            headers={"idempotency-key": "catalog-trace-001"},
        )
        self.assertEqual(mismatched_replay.status_code, 409)
        trace.append(("idempotency-conflict", mismatched_replay.status_code, "Conflict"))

        duplicate_name = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Desk lamp"}, identity,
            headers={"idempotency-key": "catalog-trace-002"},
        )
        self.assertEqual(duplicate_name.status_code, 409)
        trace.append(("duplicate-name", duplicate_name.status_code, "Conflict"))

        by_id = self.host.dispatch("catalog", "GET", "/items/" + item["id"], {}, identity)
        self.assertEqual(by_id.status_code, 200)
        self.assertEqual(by_id.body["data"], item)
        trace.append(("read-by-id", by_id.status_code, by_id.body["data"]["name"]))

        by_name = self.host.dispatch(
            "catalog", "GET", "/items/by-name/Desk%20lamp", {}, identity
        )
        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(by_name.body["data"], item)
        trace.append(("read-by-name", by_name.status_code, by_name.body["data"]["id"]))

        other_tenant = self.host.dispatch(
            "catalog", "GET", "/items/" + item["id"], {},
            self._catalog_identity("tenant-b"),
        )
        self.assertEqual(other_tenant.status_code, 404)
        trace.append(("cross-tenant-read", other_tenant.status_code, "NotFound"))

        self.assertEqual(
            [(entry[0], entry[1]) for entry in trace],
            [
                ("create", 201),
                ("idempotent-replay", 201),
                ("idempotency-conflict", 409),
                ("duplicate-name", 409),
                ("read-by-id", 200),
                ("read-by-name", 200),
                ("cross-tenant-read", 404),
            ],
        )

    def test_inventory_postgres_matches_reference_trace(self) -> None:
        identity = self._inventory_identity()
        trace = []

        created = self.host.dispatch(
            "inventory", "POST", "/stock",
            {"sku": "LAMP-001", "quantity": 12, "warehouse_id": "WH-1"},
            identity,
        )
        self.assertEqual(created.status_code, 201)
        expected = {"sku": "LAMP-001", "quantity": 12, "warehouse_id": "WH-1"}
        self.assertEqual(created.body["data"], expected)
        trace.append(("create", created.status_code, expected))

        duplicate = self.host.dispatch(
            "inventory", "POST", "/stock",
            {"sku": "LAMP-001", "quantity": 99, "warehouse_id": "WH-1"},
            identity,
        )
        self.assertEqual(duplicate.status_code, 409)
        trace.append(("duplicate-sku", duplicate.status_code, "Conflict"))

        listed = self.host.dispatch(
            "inventory", "GET", "/stock?warehouse_id=WH-1", {}, identity
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.body["data"], [expected])
        trace.append(("list", listed.status_code, len(listed.body["data"])))

        updated = self.host.dispatch(
            "inventory", "PATCH", "/stock/LAMP-001", {"quantity": 7}, identity
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.body["data"]["quantity"], 7)
        trace.append(("update", updated.status_code, 7))

        deleted = self.host.dispatch(
            "inventory", "DELETE", "/stock/LAMP-001", {}, identity
        )
        self.assertEqual(deleted.status_code, 204)
        trace.append(("delete", deleted.status_code, None))

        empty = self.host.dispatch(
            "inventory", "GET", "/stock?warehouse_id=WH-1", {}, identity
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.body["data"], [])
        trace.append(("list-after-delete", empty.status_code, 0))

        self.assertEqual(
            [(entry[0], entry[1]) for entry in trace],
            [
                ("create", 201),
                ("duplicate-sku", 409),
                ("list", 200),
                ("update", 200),
                ("delete", 204),
                ("list-after-delete", 200),
            ],
        )

    def test_unknown_route_and_method_fail_closed(self) -> None:
        self.assertEqual(self.host.service_ids, ("catalog", "inventory"))
        missing_service = self.host.dispatch(
            "unknown", "GET", "/", {}, self._catalog_identity()
        )
        self.assertEqual(missing_service.status_code, 404)
        self.assertEqual(missing_service.body["error"]["code"], "SERVICE_NOT_FOUND")

        identity = self._catalog_identity()
        unknown = self.host.dispatch("catalog", "GET", "/not-a-route", {}, identity)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.body["error"]["code"], "ROUTE_NOT_FOUND")

        wrong_method = self.host.dispatch(
            "catalog", "DELETE", "/items/by-name/example", {}, identity
        )
        self.assertEqual(wrong_method.status_code, 405)
        self.assertEqual(wrong_method.body["error"]["code"], "METHOD_NOT_ALLOWED")

        unauthorized = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Denied"},
            self._identity("tenant-c", ()),
        )
        self.assertEqual(unauthorized.status_code, 403)
        self.assertEqual(unauthorized.body["error"]["code"], "Unauthorized")


    def test_migrations_are_derived_from_catalog_and_inventory_ir(self) -> None:
        history = self.repository.migration_history()
        self.assertEqual({row["service_id"] for row in history}, {"catalog", "inventory"})
        self.assertTrue(all(row["checksum"] for row in history))
        items = self.repository.resource_schema("items")
        stock = self.repository.resource_schema("stock")
        self.assertEqual(items.key, "id")
        self.assertTrue(items.generated_key)
        self.assertEqual(items.unique_fields, ("name",))
        self.assertEqual(
            [(column.name, column.sql_type) for column in items.columns],
            [("id", "UUID"), ("name", "TEXT")],
        )
        self.assertEqual(stock.key, "sku")
        self.assertFalse(stock.generated_key)
        self.assertEqual(
            [(column.name, column.sql_type) for column in stock.columns],
            [("quantity", "BIGINT"), ("sku", "TEXT"), ("warehouse_id", "TEXT")],
        )
        with self.repository._connect() as db:
            item_columns = {
                row["column_name"]: row["data_type"]
                for row in db.execute(
                    "SELECT column_name,data_type FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name='items'",
                    (self.schema,),
                ).fetchall()
            }
            stock_columns = {
                row["column_name"]: row["data_type"]
                for row in db.execute(
                    "SELECT column_name,data_type FROM information_schema.columns "
                    "WHERE table_schema=%s AND table_name='stock'",
                    (self.schema,),
                ).fetchall()
            }
        self.assertEqual(item_columns["id"], "uuid")
        self.assertEqual(item_columns["name"], "text")
        self.assertEqual(stock_columns["quantity"], "bigint")

    def test_mutation_commits_data_audit_and_outbox_atomically(self) -> None:
        response = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Atomic lamp"},
            self._catalog_identity(),
            headers={"idempotency-key": "atomic-create-001"},
            request_id="atomic-request-001",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.repository.counts(), {
            "audit_log": 1, "outbox": 1, "idempotency_keys": 1,
        })
        self.assertEqual(self.repository.audit_events(tenant_id="tenant-a")[0]["operation"], "create_item")
        event = self.repository.outbox_events(tenant_id="tenant-a")[0]
        self.assertEqual(event["event_type"], "items.created")
        self.assertEqual(event["request_id"], "atomic-request-001")
        self.assertEqual(event["payload_json"]["data"], response.body["data"])
        self.assertEqual(
            self.repository.read("items", response.body["data"]["id"], tenant_id="tenant-a"),
            response.body["data"],
        )

    def test_mutation_failure_rolls_back_data_audit_and_outbox(self) -> None:
        def fail_after_audit(stage):
            if stage == "after_audit":
                raise OSError("injected_failure_after_audit_write")

        self.repository._fault_hook = fail_after_audit
        response = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "Must roll back"},
            self._catalog_identity(),
            headers={"idempotency-key": "atomic-rollback-001"},
            request_id="atomic-rollback-request",
        )
        self.repository._fault_hook = None
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.repository.counts(), {
            "audit_log": 0, "outbox": 0, "idempotency_keys": 0,
        })
        self.assertIsNone(
            self.repository.read_by_field("items", "name", "Must roll back", tenant_id="tenant-a")
        )

    def test_sigkill_after_commit_before_response_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "committed.marker"
            child = r"""
import sys
import time
from pathlib import Path
from agent_native import PostgresResourceRepository, RuntimeAdapters, ServiceHost, built_in_handler_registry, Grant, RequestContext

dsn, schema, marker, services_root = sys.argv[1:]
def stop_after_commit(stage):
    if stage == "after_commit":
        Path(marker).write_text("commit returned from PostgreSQL", encoding="utf-8")
        while True:
            time.sleep(1)

repository = PostgresResourceRepository(dsn, schema=schema, _fault_hook=stop_after_commit)
host = ServiceHost(
    services_root,
    handlers=built_in_handler_registry(),
    adapters=RuntimeAdapters(repository=repository, jobs=object(), events=repository),
    clock=lambda: 100,
    audit_sink=repository,
)
identity = RequestContext(
    principal_id="principal-tenant-a",
    tenant_id="tenant-a",
    now=100,
    grants=(Grant("principal-tenant-a", "tenant-a", "items.create", "/items"),),
)
host.dispatch(
    "catalog", "POST", "/items", {"name": "SIGKILL lamp"}, identity,
    headers={"idempotency-key": "sigkill-commit-001"},
    request_id="sigkill-original-request",
)
"""
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(ROOT / "src")
            process = subprocess.Popen(
                [sys.executable, "-c", child, DSN, self.schema, str(marker), str(ROOT / "services")],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 20
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if not marker.exists():
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                self.fail("child did not reach post-commit pause: " + stdout + stderr)
            process.send_signal(signal.SIGKILL)
            return_code = process.wait(timeout=10)
            self.assertEqual(return_code, -signal.SIGKILL)

        retry = self.host.dispatch(
            "catalog", "POST", "/items", {"name": "SIGKILL lamp"},
            self._catalog_identity(),
            headers={"idempotency-key": "sigkill-commit-001"},
            request_id="sigkill-retry-request",
        )
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(retry.body["data"]["name"], "SIGKILL lamp")
        self.assertEqual(self.repository.counts(), {
            "audit_log": 2, "outbox": 1, "idempotency_keys": 1,
        })


if __name__ == "__main__":
    unittest.main()
