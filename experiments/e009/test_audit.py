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

    def runtime(self, *, sink=None, handlers=None, work_store=None):
        selected_handlers = handlers
        if selected_handlers is None:
            selected_handlers = (
                build_catalog_handlers(self.repository, work_store)
                if work_store is not None
                else self.handlers
            )
        return ServiceRuntime(
            self.ir,
            handlers=selected_handlers,
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



    def test_concurrent_durable_job_admissions_share_full_commit_batches(self):
        batched_store = DurableWorkStore(
            self.repository.database,
            audit_sink=self.sink,
            max_submit_batch_size=8,
            max_submit_batch_delay_seconds=0.05,
        )
        runtime = self.runtime(work_store=batched_store)
        barrier = threading.Barrier(8)

        def submit(index):
            barrier.wait()
            return runtime.dispatch(
                "POST",
                "/items/rebuild",
                {},
                identity(),
                headers={"idempotency-key": f"batch-job-{index}"},
                request_id=f"batch-job-{index}",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(submit, range(8)))

        self.assertTrue(all(response.status_code == 202 for response in responses))
        metrics = batched_store.metrics()
        self.assertEqual(metrics["committed_submissions"], 8)
        self.assertLess(metrics["submit_batches"], 8)
        self.assertGreater(metrics["largest_submit_batch"], 1)
        self.assertEqual(self.sink.metrics()["transactional_events"], 8)
        connection = sqlite3.connect(self.repository.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0], 8)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_outbox").fetchone()[0], 8)
        finally:
            connection.close()
        for index in range(8):
            self.assertEqual(len(self.sink.list_events(request_id=f"batch-job-{index}")), 1)

    def test_audit_failure_in_one_batched_submission_does_not_rollback_its_peers(self):
        batched_store = DurableWorkStore(
            self.repository.database,
            audit_sink=self.sink,
            max_submit_batch_size=2,
            max_submit_batch_delay_seconds=0.05,
        )
        runtime = self.runtime(work_store=batched_store)
        original_write = self.sink.write_in_transaction

        def fail_one(connection, event):
            if event["request_id"] == "batch-job-fail":
                raise OSError("simulated per-item audit failure")
            return original_write(connection, event)

        self.sink.write_in_transaction = fail_one
        barrier = threading.Barrier(2)

        def submit(request_id):
            barrier.wait()
            return runtime.dispatch(
                "POST",
                "/items/rebuild",
                {},
                identity(),
                headers={"idempotency-key": request_id},
                request_id=request_id,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            failed_future = pool.submit(submit, "batch-job-fail")
            successful_future = pool.submit(submit, "batch-job-success")
            failed = failed_future.result()
            successful = successful_future.result()

        self.assertEqual(failed.status_code, 503)
        self.assertEqual(successful.status_code, 202)
        connection = sqlite3.connect(self.repository.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_outbox").fetchone()[0], 1)
        finally:
            connection.close()
        self.assertEqual(len(self.sink.list_events(request_id="batch-job-fail")), 1)
        self.assertEqual(len(self.sink.list_events(request_id="batch-job-success")), 1)
        self.assertEqual(self.sink.metrics()["transactional_events"], 1)
        self.assertEqual(batched_store.metrics()["committed_submissions"], 1)

    def test_job_outbox_idempotency_and_audit_share_one_durable_transaction(self):
        runtime = self.runtime()
        first = runtime.dispatch(
            "POST",
            "/items/rebuild",
            {},
            identity(),
            headers={"idempotency-key": "atomic-job-001"},
            request_id="atomic-job-attempt-1",
        )
        self.assertEqual(first.status_code, 202)
        first_job_id = first.body["data"]["id"]
        first_audit = self.sink.list_events(request_id="atomic-job-attempt-1")
        self.assertEqual(len(first_audit), 1)
        self.assertEqual(first_audit[0]["decision"], "allow")

        replay = runtime.dispatch(
            "POST",
            "/items/rebuild",
            {},
            identity(),
            headers={"idempotency-key": "atomic-job-001"},
            request_id="atomic-job-attempt-2",
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.body["data"]["id"], first_job_id)
        self.assertEqual(len(self.sink.list_events(request_id="atomic-job-attempt-2")), 1)

        connection = sqlite3.connect(self.repository.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_outbox").fetchone()[0], 1)
        finally:
            connection.close()
        metrics = self.sink.metrics()
        self.assertEqual(metrics["transactional_events"], 2)

    def test_atomic_audit_insert_failure_rolls_back_job_and_outbox_then_fails_closed(self):
        def fail_insert(_connection, _event):
            raise OSError("simulated audit insert failure")

        self.sink.write_in_transaction = fail_insert
        runtime = self.runtime()
        response = runtime.dispatch(
            "POST",
            "/items/rebuild",
            {},
            identity(),
            headers={"idempotency-key": "atomic-job-fail-001"},
            request_id="atomic-job-fail-001",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.body["error"]["code"], "ServiceUnavailable")
        connection = sqlite3.connect(self.repository.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_jobs").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM durable_outbox").fetchone()[0], 0)
        finally:
            connection.close()
        fallback = self.sink.list_events(request_id="atomic-job-fail-001")
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]["decision"], "allow")

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
