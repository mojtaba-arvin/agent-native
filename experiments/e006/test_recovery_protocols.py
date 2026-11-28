import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from durable_queue import DurableQueue, StaleLease
from recovery_protocols import ExternalEffectHarness, SimulatedProcessCrash


def _race_claim(path: str, worker: str, barrier, output) -> None:
    queue = DurableQueue(path)
    barrier.wait()
    output.put(queue.claim(worker_id=worker, now=10, lease_seconds=20))


def _die_inside_transaction(path: str) -> None:
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.execute("BEGIN IMMEDIATE")
    db.execute(
        "INSERT INTO local_state(state_key,value) VALUES ('crash-state',99)"
    )
    db.execute(
        """INSERT INTO effect_ledger(
           effect_key,payload_hash,state_key,amount,resulting_value
           ) VALUES ('crash-effect','hash','crash-state',99,99)"""
    )
    db.execute("UPDATE tasks SET status='completed' WHERE id='crash-task'")
    os._exit(73)


class MultiProcessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "queue.sqlite3"
        self.queue = DurableQueue(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_independent_processes_cannot_claim_the_same_task(self):
        self.queue.submit(task_id="one", idempotency_key="one", payload={},
                          now=1, deadline_at=100)
        context = multiprocessing.get_context("fork")
        barrier = context.Barrier(3)
        output = context.Queue()
        workers = [
            context.Process(target=_race_claim, args=(str(self.path), f"w{i}", barrier, output))
            for i in range(2)
        ]
        for process in workers:
            process.start()
        barrier.wait()
        results = [output.get(timeout=10) for _ in workers]
        for process in workers:
            process.join(timeout=10)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.queue.get_task("one")["lease_token"], 1)

    def test_abrupt_process_death_rolls_back_all_uncommitted_effect_writes(self):
        self.queue.submit(task_id="crash-task", idempotency_key="crash-key",
                          payload={}, now=1, deadline_at=100)
        process = multiprocessing.get_context("fork").Process(
            target=_die_inside_transaction, args=(str(self.path),)
        )
        process.start()
        process.join(timeout=10)
        self.assertEqual(process.exitcode, 73)
        reopened = DurableQueue(self.path)
        self.assertEqual(reopened.get_task("crash-task")["status"], "queued")
        self.assertEqual(reopened.get_state("crash-state"), 0)
        self.assertIsNone(reopened.get_effect("crash-effect"))

    def test_expired_lease_recovery_fences_original_process_identity(self):
        self.queue.submit(task_id="fenced", idempotency_key="fenced-key",
                          payload={}, now=1, deadline_at=100)
        old = self.queue.claim(worker_id="old-process", now=10, lease_seconds=5)
        new = DurableQueue(self.path).claim(
            worker_id="recovery-process", now=16, lease_seconds=5
        )
        self.assertEqual((old["lease_token"], new["lease_token"]), (1, 2))
        with self.assertRaises(StaleLease):
            self.queue.complete_with_increment(
                task_id="fenced", worker_id="old-process", lease_token=1,
                now=16, effect_key="must-not-commit", state_key="balance", amount=8,
            )
        self.assertEqual(self.queue.get_state("balance"), 0)


class ExternalEffectRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.app = root / "application.sqlite3"
        self.broker = root / "broker.sqlite3"
        self.harness = ExternalEffectHarness(self.app, self.broker)

    def tearDown(self):
        self.temp.cleanup()

    def test_business_fact_and_outbox_intent_commit_together(self):
        self.harness.submit(fact_id="order-1", event_id="event-1",
                            payload={"increment": 4})
        with sqlite3.connect(self.app) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM business_facts").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)
        self.assertEqual(self.harness.publish_one(worker="relay", now=1, lease_seconds=5),
                         "event-1")

    def test_relay_crash_after_broker_ack_causes_duplicate_delivery_not_lost_intent(self):
        self.harness.submit(fact_id="order-1", event_id="event-1",
                            payload={"increment": 4})
        with self.assertRaisesRegex(SimulatedProcessCrash, "after_broker_ack"):
            self.harness.publish_one(worker="relay-a", now=1, lease_seconds=5,
                                     crash_after_broker_ack=True)
        self.assertEqual(self.harness.publish_one(worker="relay-b", now=7, lease_seconds=5),
                         "event-1")
        deliveries = self.harness.deliveries()
        self.assertEqual(len(deliveries), 2)
        self.assertTrue(self.harness.consume(delivery_id=1, consumer="billing", now=8))
        self.assertFalse(self.harness.consume(delivery_id=2, consumer="billing", now=9))
        self.assertEqual(self.harness.effect_total("billing"), 4)

    def test_consumer_crash_after_commit_before_ack_is_safe_on_redelivery(self):
        self.harness.submit(fact_id="order-1", event_id="event-1",
                            payload={"increment": 6})
        self.harness.publish_one(worker="relay", now=1, lease_seconds=5)
        with self.assertRaisesRegex(SimulatedProcessCrash, "before_ack"):
            self.harness.consume(delivery_id=1, consumer="ledger", now=2,
                                 crash_before_broker_ack=True)
        self.assertEqual(self.harness.effect_total("ledger"), 6)
        self.assertFalse(self.harness.consume(delivery_id=1, consumer="ledger", now=3))
        self.assertEqual(self.harness.effect_total("ledger"), 6)
        self.assertEqual(self.harness.deliveries()[0]["acknowledged"], 1)

    def test_same_event_id_with_changed_payload_is_rejected(self):
        self.harness.submit(fact_id="order-1", event_id="event-1",
                            payload={"increment": 2})
        with self.assertRaisesRegex(ValueError, "payload_conflict"):
            self.harness.submit(fact_id="order-2", event_id="event-1",
                                payload={"increment": 3})


if __name__ == "__main__":
    unittest.main()
