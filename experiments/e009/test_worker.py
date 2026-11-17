from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repository import SQLiteCatalogRepository
from worker import CatalogWorker, OutboxRelay
from work_store import DurableWorkStore, StaleJobLease


class CatalogWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "kernel.sqlite3"
        self.repository = SQLiteCatalogRepository(self.database)
        self.store = DurableWorkStore(self.database)
        self.worker = CatalogWorker(self.repository, self.store, lease_seconds=10)

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    def test_worker_claims_and_completes_catalog_rebuild(self):
        self.repository.create_item(
            tenant_id="tenant-a",
            name="Desk lamp",
            idempotency_key="item-1",
            now=1,
        )
        self.repository.create_item(
            tenant_id="tenant-a",
            name="Floor lamp",
            idempotency_key="item-2",
            now=1,
        )
        job, replayed = self.store.submit_job(
            tenant_id="tenant-a",
            task_type="catalog.rebuild",
            payload={"requested_by": "operator"},
            idempotency_key="rebuild-1",
            now=2,
            deadline_at=100,
            max_attempts=3,
        )
        self.assertFalse(replayed)
        outcome = self.worker.run_once(worker_id="worker-1", now=3)
        self.assertTrue(outcome.claimed)
        self.assertEqual(outcome.task_id, job["task_id"])
        self.assertEqual(outcome.state, "completed")
        self.assertEqual(outcome.result["items_seen"], 2)
        saved = self.store.get_job(tenant_id="tenant-a", task_id=job["task_id"])
        self.assertEqual(saved["state"], "completed")
        self.assertEqual(saved["result"]["items_seen"], 2)

    def test_worker_does_not_execute_jobs_for_another_tenant(self):
        job, _ = self.store.submit_job(
            tenant_id="tenant-b",
            task_type="catalog.rebuild",
            payload={},
            idempotency_key="tenant-b-job",
            now=1,
            deadline_at=100,
        )
        # Worker identity is selected by the trusted claim context; the job
        # carries its tenant and the handler queries only that tenant.
        self.repository.create_item(
            tenant_id="tenant-a", name="A", idempotency_key="a", now=1
        )
        self.repository.create_item(
            tenant_id="tenant-b", name="B", idempotency_key="b", now=1
        )
        outcome = self.worker.run_once(worker_id="worker-tenant-b", now=2)
        self.assertEqual(outcome.task_id, job["task_id"])
        self.assertEqual(outcome.result["items_seen"], 1)

    def test_outbox_relay_redelivery_is_inbox_deduplicated(self):
        job, _ = self.store.submit_job(
            tenant_id="tenant-a",
            task_type="catalog.rebuild",
            payload={},
            idempotency_key="relay-job",
            now=1,
            deadline_at=100,
        )
        outcome = self.worker.run_once(worker_id="worker-1", now=2)
        self.assertEqual(outcome.state, "completed")
        relay = OutboxRelay(self.store, consumer_id="catalog-metrics", lease_seconds=5)

        submitted_event = relay.run_once(relay_id="relay-a", now=3)
        self.assertTrue(submitted_event.claimed)
        self.assertTrue(submitted_event.acknowledged)

        first_delivery = relay.run_once(
            relay_id="relay-a",
            now=4,
            acknowledge=False,
        )
        self.assertTrue(first_delivery.claimed)
        self.assertFalse(first_delivery.duplicate)
        self.assertEqual(first_delivery.total, 1)

        second_delivery = relay.run_once(
            relay_id="relay-b",
            now=10,
            acknowledge=True,
        )
        self.assertTrue(second_delivery.claimed)
        self.assertTrue(second_delivery.duplicate)
        self.assertEqual(second_delivery.total, 1)
        self.assertEqual(
            self.store.consumer_total(
                consumer_id="catalog-metrics",
                state_key="catalog.rebuild",
            ),
            1,
        )

    def test_stop_request_is_not_acknowledged_by_expired_lease_alone(self):
        job, _ = self.store.submit_job(
            tenant_id="tenant-a",
            task_type="catalog.rebuild",
            payload={},
            idempotency_key="stop-job",
            now=1,
            deadline_at=100,
        )
        claim = self.store.claim_job(worker_id="worker-1", now=2, lease_seconds=2)
        self.assertEqual(claim["task_id"], job["task_id"])
        self.assertEqual(self.store.request_expired_job_stops(now=5), 1)
        pending = self.store.get_job(tenant_id="tenant-a", task_id=job["task_id"])
        self.assertEqual(pending["state"], "cancellation_requested")
        self.assertEqual(pending["lease_owner"], "worker-1")

        stopped = self.store.worker_crashed(
            task_id=job["task_id"],
            worker_id="worker-1",
            lease_token=claim["lease_token"],
            now=6,
        )
        self.assertEqual(stopped["state"], "queued")


if __name__ == "__main__":
    unittest.main()
