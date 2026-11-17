from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from pathlib import Path

from repository import SQLiteCatalogRepository
from worker import CatalogWorker, OutboxRelay
from work_store import DurableWorkStore, StaleJobLease

ROOT = Path(__file__).resolve().parents[2]


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

    def test_single_process_host_runs_http_worker_and_outbox_lifecycle(self):
        token = "local-demo-token-aaaaaaaaaaaaaaaaaaaa"
        command = [
            sys.executable,
            str(Path(__file__).with_name("serve.py")),
            "--database",
            str(self.database),
            "--port",
            "0",
            "--worker-poll-seconds",
            "0.05",
            "--relay-poll-seconds",
            "0.05",
        ]
        environment = {**os.environ, "AGENT_NATIVE_DEMO_TOKEN": token}
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            startup = process.stdout.readline()
            match = re.search(r"http://127\.0\.0\.1:(\d+)", startup)
            self.assertIsNotNone(match, startup)
            base_url = f"http://127.0.0.1:{match.group(1)}"

            def request(method, path, body=None):
                raw = None if body is None else json.dumps(body).encode("utf-8")
                headers = {"Authorization": f"Bearer {token}"}
                if raw is not None:
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(
                    base_url + path,
                    data=raw,
                    headers=headers,
                    method=method,
                )
                try:
                    with urllib.request.urlopen(req, timeout=3) as response:
                        return response.status, json.loads(response.read())
                except urllib.error.HTTPError as error:
                    return error.code, json.loads(error.read())

            submitted_status, submitted = request("POST", "/items/rebuild", {})
            self.assertEqual(submitted_status, 202)
            task_id = submitted["data"]["id"]

            deadline = time.monotonic() + 8
            final = None
            while time.monotonic() < deadline:
                status, final = request("GET", f"/jobs/{task_id}")
                if status == 200 and final["data"]["state"] == "completed":
                    break
                time.sleep(0.05)
            self.assertIsNotNone(final)
            self.assertEqual(final["data"]["state"], "completed")

            observer_deadline = time.monotonic() + 5
            observed = 0
            while time.monotonic() < observer_deadline:
                observed = DurableWorkStore(self.database).consumer_total(
                    consumer_id="catalog-local-observer",
                    state_key="catalog.rebuild",
                )
                if observed == 1:
                    break
                time.sleep(0.05)
            self.assertEqual(observed, 1)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            stderr = process.stderr.read()
            self.assertEqual(process.returncode, 0, stderr)

    def test_outbox_retries_consumer_failures_then_dead_letters(self):
        self.store.submit_job(
            tenant_id="tenant-a",
            task_type="catalog.rebuild",
            payload={},
            idempotency_key="relay-retry-job",
            now=1,
            deadline_at=100,
        )
        relay = OutboxRelay(self.store, consumer_id="retry-observer", lease_seconds=5)
        outcomes = []
        for attempt in range(1, 9):
            now = attempt + 1
            with patch.object(
                self.store,
                "consume_delta_event",
                side_effect=OSError("consumer storage unavailable"),
            ):
                outcome = relay.run_once(relay_id="retry-relay", now=now)
            outcomes.append(outcome)
            self.assertTrue(outcome.claimed)
            self.assertFalse(outcome.acknowledged)
            self.assertEqual(outcome.failure_class, "OSERROR")
            self.assertEqual(outcome.retry_scheduled, attempt < 8)

        self.assertEqual(self.store.outbox_counts()["failed"], 1)
        self.assertFalse(relay.run_once(relay_id="retry-relay", now=20).claimed)

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
