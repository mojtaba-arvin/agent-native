from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from audit import SQLiteAuditSink
from catalog import build_catalog_handlers
from kernel import ServiceRuntime, load_service_ir
from repository import SQLiteCatalogRepository
from work_store import DurableWorkStore
from security_model import Grant, RequestContext


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (Path(__file__).parent / "catalog.an").read_text(encoding="utf-8")
TRUSTED_EFFECTS = {
    "repository.read", "repository.write", "queue.submit", "queue.read", "queue.cancel",
}


def identity(*, grants=True):
    values = (
        Grant("user-a", "tenant-a", "items.create", "/items"),
        Grant("user-a", "tenant-a", "items.read", "/items"),
        Grant("user-a", "tenant-a", "jobs.submit", "/items"),
        Grant("user-a", "tenant-a", "jobs.read", "/jobs"),
        Grant("user-a", "tenant-a", "jobs.cancel", "/jobs"),
    ) if grants else ()
    return RequestContext(
        principal_id="user-a",
        tenant_id="tenant-a",
        now=100,
        grants=values,
    )


class SQLiteAuditSinkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "catalog.sqlite3"
        self.repository = SQLiteCatalogRepository(self.database)
        self.sink = SQLiteAuditSink(self.repository.database)
        self.work_store = DurableWorkStore(
            self.repository.database,
            audit_sink=self.sink,
        )
        self.handlers = build_catalog_handlers(self.repository, self.work_store)
        self.ir = load_service_ir(SOURCE)

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    def runtime(self, *, sink=None, handlers=None):
        return ServiceRuntime(
            self.ir,
            handlers=self.handlers if handlers is None else handlers,
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: 100,
            audit_sink=self.sink if sink is None else sink,
        )

    def test_allow_and_deny_decisions_are_persisted_before_handler_and_survive_reopen(self):
        handlers = dict(self.handlers)
        original = handlers["create_item"]

        def checked_create(context):
            events = self.sink.list_events(request_id=context.request_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["decision"], "allow")
            return original(context)

        handlers["create_item"] = checked_create
        runtime = self.runtime(handlers=handlers)
        created = runtime.dispatch(
            "POST",
            "/items",
            {"name": "Desk lamp"},
            identity(),
            headers={"idempotency-key": "audit-create-1"},
            request_id="audit-allow-1",
        )
        self.assertEqual(created.status_code, 201)

        denied = runtime.dispatch(
            "POST",
            "/items",
            {"name": "Forbidden"},
            identity(grants=False),
            headers={"idempotency-key": "audit-create-2"},
            request_id="audit-deny-1",
        )
        self.assertEqual(denied.status_code, 403)

        reopened = SQLiteAuditSink(self.repository.database)
        events = reopened.list_events()
        self.assertEqual([event["request_id"] for event in events], [
            "audit-allow-1", "audit-deny-1",
        ])
        self.assertEqual([event["decision"] for event in events], ["allow", "deny"])
        self.assertEqual(events[1]["reason_code"], "MISSING_CAPABILITY")
        for event in events:
            self.assertNotIn("authorization", event)
            self.assertNotIn("token", event)
            self.assertNotIn("body", event)

    def test_audit_storage_failure_fails_closed_before_handler(self):
        invoked = []

        class FailingSink:
            def __call__(self, _event):
                raise OSError("audit store unavailable")

        handlers = dict(self.handlers)
        original = handlers["create_item"]

        def checked_create(context):
            invoked.append(context.request_id)
            return original(context)

        handlers["create_item"] = checked_create
        runtime = self.runtime(sink=FailingSink(), handlers=handlers)
        response = runtime.dispatch(
            "POST",
            "/items",
            {"name": "Must not be written"},
            identity(),
            headers={"idempotency-key": "audit-fail-1"},
            request_id="audit-fail-1",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.body["error"]["code"], "AUDIT_UNAVAILABLE")
        self.assertEqual(invoked, [])

    def test_concurrent_appends_are_complete_and_ordered(self):
        def write(index):
            self.sink({
                "principal_id": "user-a",
                "tenant_id": "tenant-a",
                "operation": "get_item",
                "resource": f"/items/{index}",
                "requested_effects": ["repository.read"],
                "decision": "allow",
                "reason_code": "ALLOW",
                "request_id": f"concurrent-{index}",
                "timestamp": 100 + index,
            })

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(24)))
        events = self.sink.list_events()
        self.assertEqual(len(events), 24)
        self.assertEqual(len({event["request_id"] for event in events}), 24)


    def test_concurrent_callers_share_durable_group_commit(self):
        barrier = threading.Barrier(8)
        sink = SQLiteAuditSink(
            self.repository.database,
            max_batch_size=8,
            max_batch_delay_seconds=0.020,
        )

        def write(index):
            event = {
                "principal_id": "user-a",
                "tenant_id": "tenant-a",
                "operation": "get_item",
                "resource": f"/items/group-{index}",
                "requested_effects": ["repository.read"],
                "decision": "allow",
                "reason_code": "ALLOW",
                "request_id": f"group-commit-{index}",
                "timestamp": 200 + index,
            }
            barrier.wait(timeout=5)
            sink(event)
            self.assertEqual(len(sink.list_events(request_id=event["request_id"])), 1)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(8)))

        metrics = sink.metrics()
        self.assertEqual(metrics["committed_events"], 8)
        self.assertLess(metrics["committed_batches"], 8)
        self.assertGreater(metrics["largest_batch"], 1)
        self.assertEqual(len(sink.list_events()), 8)

    def test_group_commit_failure_fails_every_waiting_caller_closed(self):
        barrier = threading.Barrier(8)
        sink = SQLiteAuditSink(
            self.repository.database,
            max_batch_size=8,
            max_batch_delay_seconds=0.020,
        )

        def fail_batch(_batch):
            raise OSError("simulated durable commit failure")

        sink._write_batch = fail_batch

        def write(index):
            event = {
                "principal_id": "user-a",
                "tenant_id": "tenant-a",
                "operation": "get_item",
                "resource": f"/items/fail-{index}",
                "requested_effects": ["repository.read"],
                "decision": "allow",
                "reason_code": "ALLOW",
                "request_id": f"group-failure-{index}",
                "timestamp": 300 + index,
            }
            barrier.wait(timeout=5)
            with self.assertRaisesRegex(OSError, "audit_batch_commit_failed"):
                sink(event)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(8)))

        self.assertEqual(sink.list_events(), [])
        self.assertEqual(sink.metrics()["committed_events"], 0)

    def test_audit_rows_reject_update_and_delete(self):
        self.sink({
            "principal_id": "user-a",
            "tenant_id": "tenant-a",
            "operation": "get_item",
            "resource": "/items/1",
            "requested_effects": ["repository.read"],
            "decision": "allow",
            "reason_code": "ALLOW",
            "request_id": "append-only",
            "timestamp": 100,
        })
        connection = sqlite3.connect(self.repository.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE audit_events SET reason_code = 'FORGED' WHERE request_id = ?",
                    ("append-only",),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM audit_events WHERE request_id = ?",
                    ("append-only",),
                )
        finally:
            connection.close()
        self.assertEqual(
            self.sink.list_events(request_id="append-only")[0]["reason_code"],
            "ALLOW",
        )


if __name__ == "__main__":
    unittest.main()
