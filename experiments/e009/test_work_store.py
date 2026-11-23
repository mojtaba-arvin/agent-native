from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repository import SQLiteCatalogRepository
from work_store import (
    DurableWorkStore,
    InboxConflict,
    JobBackpressure,
    JobConflict,
    StaleJobLease,
    StaleOutboxLease,
)


class DurableWorkStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "shared.sqlite3"
        self.repository = SQLiteCatalogRepository(self.database)
        self.store = DurableWorkStore(self.database)

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    def submit(self, *, tenant="tenant-a", key="job-key", now=0, deadline=100, attempts=3, payload=None):
        return self.store.submit_job(
            tenant_id=tenant,
            task_type="catalog.rebuild",
            payload=payload or {"requested_by": "operator"},
            idempotency_key=key,
            now=now,
            deadline_at=deadline,
            max_attempts=attempts,
        )


    def test_idle_worker_and_relay_polls_do_not_acquire_write_lock(self):
        statements = []
        original_connect = self.store._connect

        def traced_connect():
            connection = original_connect()
            connection.set_trace_callback(statements.append)
            return connection

        self.store._connect = traced_connect
        self.assertIsNone(
            self.store.claim_job(worker_id="idle-worker", now=1, lease_seconds=30)
        )
        self.assertIsNone(
            self.store.claim_outbox(relay_id="idle-relay", now=1, lease_seconds=30)
        )
        self.assertFalse(
            any(statement.strip().upper().startswith("BEGIN IMMEDIATE") for statement in statements),
            statements,
        )

    def test_job_submission_is_idempotent_and_tenant_scoped(self):
        first, replayed = self.submit()
        replay, replayed_again = self.submit(now=1)
        other_tenant, other_replayed = self.submit(tenant="tenant-b", now=1)

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(first["task_id"], replay["task_id"])
        self.assertFalse(other_replayed)
        self.assertNotEqual(first["task_id"], other_tenant["task_id"])

        with self.assertRaises(JobConflict):
            self.submit(payload={"requested_by": "other"}, now=2)

    def test_concurrent_duplicate_job_submissions_commit_one_job(self):
        def submit_one(_index):
            return self.submit(key="concurrent-key", now=10)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(submit_one, range(8)))
        task_ids = {job["task_id"] for job, _replay in results}
        replay_flags = [replay for _job, replay in results]
        self.assertEqual(len(task_ids), 1)
        self.assertEqual(replay_flags.count(False), 1)
        self.assertEqual(replay_flags.count(True), 7)

    def test_claim_lease_expiry_requires_stop_ack_and_fences_old_worker(self):
        job, _ = self.submit()
        first = self.store.claim_job(worker_id="worker-a", now=1, lease_seconds=5)
        self.assertEqual(first["task_id"], job["task_id"])
        self.assertEqual(first["lease_token"], 1)
        self.assertEqual(self.store.request_expired_job_stops(now=7), 1)

        stopping = self.store.get_job(tenant_id="tenant-a", task_id=job["task_id"])
        self.assertEqual(stopping["state"], "cancellation_requested")
        self.assertEqual(stopping["lease_owner"], "worker-a")

        acknowledged = self.store.worker_crashed(
            task_id=job["task_id"],
            worker_id="worker-a",
            lease_token=first["lease_token"],
            now=7,
        )
        self.assertEqual(acknowledged["state"], "queued")
        second = self.store.claim_job(worker_id="worker-b", now=8, lease_seconds=20)
        self.assertEqual(second["lease_token"], 2)

        with self.assertRaises(StaleJobLease):
            self.store.complete_job(
                task_id=job["task_id"],
                worker_id="worker-a",
                lease_token=first["lease_token"],
                now=9,
                result={"items_seen": 0},
            )
        completed = self.store.complete_job(
            task_id=job["task_id"],
            worker_id="worker-b",
            lease_token=second["lease_token"],
            now=9,
            result={"items_seen": 2},
        )
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["result"], {"items_seen": 2})

    def test_cancel_running_job_retains_lease_until_stop_ack(self):
        job, _ = self.submit(key="cancel-key")
        claim = self.store.claim_job(worker_id="worker-a", now=1, lease_seconds=20)
        cancelled = self.store.cancel_job(
            tenant_id="tenant-a",
            task_id=job["task_id"],
            now=2,
        )
        self.assertEqual(cancelled["state"], "cancellation_requested")
        self.assertEqual(cancelled["lease_owner"], "worker-a")

        with self.assertRaises(StaleJobLease):
            self.store.complete_job(
                task_id=job["task_id"],
                worker_id="worker-a",
                lease_token=claim["lease_token"],
                now=3,
                result={"items_seen": 0},
            )
        stopped = self.store.acknowledge_stopped(
            task_id=job["task_id"],
            worker_id="worker-a",
            lease_token=claim["lease_token"],
            now=4,
        )
        self.assertEqual(stopped["state"], "cancelled")
        self.assertIsNone(stopped["lease_owner"])

    def test_deadline_expiry_cancels_running_work_after_stop_ack(self):
        queued, _ = self.submit(key="queued-deadline", deadline=5)
        expired = self.store.request_expirations(now=5)
        self.assertEqual(expired["queued_expired"], 1)
        queued_row = self.store.get_job(tenant_id="tenant-a", task_id=queued["task_id"])
        self.assertEqual(queued_row["state"], "expired")

        running, _ = self.submit(key="running-deadline", now=6, deadline=50)
        claim = self.store.claim_job(worker_id="worker-a", now=7, lease_seconds=60)
        self.assertEqual(claim["task_id"], running["task_id"])
        running_expiry = self.store.request_expirations(now=51)
        self.assertEqual(running_expiry["running_stop_requested"], 1)
        pending_stop = self.store.get_job(tenant_id="tenant-a", task_id=running["task_id"])
        self.assertEqual(pending_stop["state"], "cancellation_requested")
        self.assertEqual(pending_stop["terminal_reason"], "deadline")

        stopped = self.store.acknowledge_stopped(
            task_id=running["task_id"],
            worker_id="worker-a",
            lease_token=claim["lease_token"],
            now=52,
        )
        self.assertEqual(stopped["state"], "expired")

    def test_failure_retries_then_becomes_terminal(self):
        job, _ = self.submit(key="retry-key", attempts=2)
        first = self.store.claim_job(worker_id="worker-a", now=1, lease_seconds=20)
        retried = self.store.fail_job(
            task_id=job["task_id"],
            worker_id="worker-a",
            lease_token=first["lease_token"],
            now=2,
            error_code="TRANSIENT",
            retry_delay=3,
        )
        self.assertEqual(retried["state"], "queued")
        self.assertEqual(retried["available_at"], 5)
        self.assertIsNone(self.store.claim_job(worker_id="worker-b", now=4, lease_seconds=20))

        second = self.store.claim_job(worker_id="worker-b", now=5, lease_seconds=20)
        terminal = self.store.fail_job(
            task_id=job["task_id"],
            worker_id="worker-b",
            lease_token=second["lease_token"],
            now=6,
            error_code="TRANSIENT",
        )
        self.assertEqual(terminal["state"], "failed")

    def test_outbox_reclaims_expired_lease_and_fences_stale_relay(self):
        job, _ = self.submit(key="outbox-key")
        claim = self.store.claim_job(worker_id="worker-a", now=1, lease_seconds=20)
        self.store.complete_job(
            task_id=job["task_id"],
            worker_id="worker-a",
            lease_token=claim["lease_token"],
            now=2,
            result={"items_seen": 1},
        )

        submitted = self.store.claim_outbox(relay_id="relay-a", now=3, lease_seconds=5)
        self.assertEqual(submitted["topic"], "work.submitted")
        self.store.ack_outbox(
            event_id=submitted["event_id"],
            relay_id="relay-a",
            lease_token=submitted["lease_token"],
            now=4,
        )

        first = self.store.claim_outbox(relay_id="relay-a", now=5, lease_seconds=5)
        self.assertEqual(first["topic"], "work.completed")
        consumed = self.store.consume_delta_event(
            consumer_id="catalog-observer",
            event_id=first["event_id"],
            payload=first["payload"],
            now=6,
        )
        self.assertFalse(consumed["duplicate"])
        self.assertEqual(consumed["total"], 1)

        second = self.store.claim_outbox(relay_id="relay-b", now=11, lease_seconds=10)
        self.assertEqual(second["event_id"], first["event_id"])
        self.assertEqual(second["lease_token"], first["lease_token"] + 1)
        replay = self.store.consume_delta_event(
            consumer_id="catalog-observer",
            event_id=second["event_id"],
            payload=second["payload"],
            now=12,
        )
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["total"], 1)

        with self.assertRaises(StaleOutboxLease):
            self.store.ack_outbox(
                event_id=first["event_id"],
                relay_id="relay-a",
                lease_token=first["lease_token"],
                now=12,
            )
        self.store.ack_outbox(
            event_id=second["event_id"],
            relay_id="relay-b",
            lease_token=second["lease_token"],
            now=12,
        )
        self.assertEqual(self.store.consumer_total(
            consumer_id="catalog-observer",
            state_key="catalog.rebuild",
        ), 1)

    def test_inbox_conflicting_event_reuse_is_rejected(self):
        envelope = {"payload": {"task_id": "job-1"}, "state_key": "work.done", "amount": 1}
        first = self.store.consume_delta_event(
            consumer_id="consumer-a", event_id="event-1", payload=envelope, now=1
        )
        duplicate = self.store.consume_delta_event(
            consumer_id="consumer-a", event_id="event-1", payload=envelope, now=2
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        with self.assertRaises(InboxConflict):
            self.store.consume_delta_event(
                consumer_id="consumer-a",
                event_id="event-1",
                payload={**envelope, "amount": 2},
                now=3,
            )
        self.assertEqual(self.store.consumer_total(
            consumer_id="consumer-a", state_key="work.done"
        ), 1)

    def test_outstanding_limit_rejects_new_work_but_allows_idempotent_replay(self):
        constrained = DurableWorkStore(
            self.database,
            max_outstanding=1,
            max_concurrency=1,
        )
        first, replay = constrained.submit_job(
            tenant_id="tenant-a",
            task_type="catalog.rebuild",
            payload={"requested_by": "operator"},
            idempotency_key="capacity-1",
            now=1,
            deadline_at=100,
        )
        self.assertFalse(replay)
        same, replayed = constrained.submit_job(
            tenant_id="tenant-a",
            task_type="catalog.rebuild",
            payload={"requested_by": "operator"},
            idempotency_key="capacity-1",
            now=2,
            deadline_at=100,
        )
        self.assertTrue(replayed)
        self.assertEqual(same["task_id"], first["task_id"])
        with self.assertRaises(JobBackpressure):
            constrained.submit_job(
                tenant_id="tenant-a",
                task_type="catalog.rebuild",
                payload={"requested_by": "operator"},
                idempotency_key="capacity-2",
                now=2,
                deadline_at=100,
            )

    def test_running_limit_includes_cancellation_until_stop_is_acknowledged(self):
        constrained = DurableWorkStore(
            self.database,
            max_outstanding=5,
            max_concurrency=1,
        )
        first, _ = constrained.submit_job(
            tenant_id="tenant-a", task_type="catalog.rebuild", payload={},
            idempotency_key="running-1", now=1, deadline_at=100,
        )
        second, _ = constrained.submit_job(
            tenant_id="tenant-a", task_type="catalog.rebuild", payload={},
            idempotency_key="running-2", now=1, deadline_at=100,
        )
        claim = constrained.claim_job(worker_id="worker-1", now=2, lease_seconds=30)
        self.assertIn(claim["task_id"], {first["task_id"], second["task_id"]})
        remaining_task_id = (
            second["task_id"] if claim["task_id"] == first["task_id"] else first["task_id"]
        )
        self.assertIsNone(constrained.claim_job(worker_id="worker-2", now=3, lease_seconds=30))

        constrained.cancel_job(
            tenant_id="tenant-a",
            task_id=claim["task_id"],
            now=4,
        )
        self.assertIsNone(constrained.claim_job(worker_id="worker-2", now=5, lease_seconds=30))
        stopped = constrained.acknowledge_stopped(
            task_id=claim["task_id"],
            worker_id="worker-1",
            lease_token=claim["lease_token"],
            now=6,
        )
        self.assertEqual(stopped["state"], "cancelled")
        next_claim = constrained.claim_job(worker_id="worker-2", now=7, lease_seconds=30)
        self.assertEqual(next_claim["task_id"], remaining_task_id)

    def test_invalid_job_envelopes_and_deadlines_are_rejected(self):
        with self.assertRaises(ValueError):
            self.submit(payload=["not", "an", "object"])
        with self.assertRaises(ValueError):
            self.submit(now=10, deadline=10)
        with self.assertRaises(ValueError):
            self.submit(attempts=True)


    def test_recovery_metrics_are_durable_and_count_retries_and_duplicate_delivery(self):
        job, replayed = self.submit(key="metrics-job", now=1)
        self.assertFalse(replayed)
        first_claim = self.store.claim_job(worker_id="worker-a", now=2, lease_seconds=10)
        self.assertEqual(first_claim["task_id"], job["task_id"])
        self.store.fail_job(
            task_id=job["task_id"], worker_id="worker-a",
            lease_token=first_claim["lease_token"], now=3,
            error_code="TRANSIENT", retry_delay=0,
        )
        second_claim = self.store.claim_job(worker_id="worker-b", now=4, lease_seconds=10)
        self.assertEqual(second_claim["attempts"], 2)

        first_event = self.store.claim_outbox(relay_id="relay-a", now=6, lease_seconds=1)
        self.assertIsNotNone(first_event)
        envelope = first_event["payload"]
        first_delivery = self.store.consume_delta_event(
            consumer_id="metrics-consumer", event_id=first_event["event_id"],
            payload=envelope, now=6,
        )
        duplicate_delivery = self.store.consume_delta_event(
            consumer_id="metrics-consumer", event_id=first_event["event_id"],
            payload=envelope, now=7,
        )
        self.assertFalse(first_delivery["duplicate"])
        self.assertTrue(duplicate_delivery["duplicate"])
        reclaimed = self.store.claim_outbox(relay_id="relay-b", now=7, lease_seconds=5)
        self.assertEqual(reclaimed["event_id"], first_event["event_id"])
        self.store.ack_outbox(
            event_id=reclaimed["event_id"], relay_id="relay-b",
            lease_token=reclaimed["lease_token"], now=8,
        )

        metrics_before = self.store.recovery_metrics(now=8)
        self.assertEqual(metrics_before["jobs"]["multi_attempt_jobs"], 1)
        self.assertGreaterEqual(metrics_before["outbox"]["redeliveries"], 1)
        self.assertEqual(metrics_before["inbox"]["duplicate_deliveries"], 1)

        reopened = DurableWorkStore(self.database)
        metrics_after = reopened.recovery_metrics(now=8)
        self.assertEqual(metrics_after, metrics_before)

if __name__ == "__main__":
    unittest.main()
