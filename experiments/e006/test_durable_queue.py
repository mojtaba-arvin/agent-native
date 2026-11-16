import tempfile
import threading
import unittest
from pathlib import Path

from durable_queue import DurableQueue, IdempotencyConflict, StaleLease


class DurableQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "queue.sqlite3"
        self.queue = DurableQueue(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, task_id="task-1", key="idem-1", payload=None, deadline=1000, max_attempts=3):
        return self.queue.submit(
            task_id=task_id, idempotency_key=key,
            payload={"job": "reconcile"} if payload is None else payload,
            now=10, deadline_at=deadline, max_attempts=max_attempts,
        )

    def claim(self, worker="worker-a", now=10, lease=5):
        return self.queue.claim(worker_id=worker, now=now, lease_seconds=lease)

    def test_submit_is_idempotent_and_rejects_key_payload_collision(self):
        first = self.submit()
        duplicate = self.submit(task_id="task-ignored")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["task"]["id"], "task-1")
        with self.assertRaises(IdempotencyConflict):
            self.submit(payload={"job": "different"})

    def test_claim_uses_monotonic_fencing_tokens_after_lease_expiry(self):
        self.submit()
        first = self.claim(worker="worker-a", now=10, lease=5)
        reopened = DurableQueue(self.path)
        second = reopened.claim(worker_id="worker-b", now=16, lease_seconds=5)
        self.assertEqual(first["lease_token"], 1)
        self.assertEqual(second["lease_token"], 2)
        with self.assertRaises(StaleLease):
            self.queue.complete_with_increment(
                task_id="task-1", worker_id="worker-a", lease_token=1,
                now=16, effect_key="effect-1", state_key="balance", amount=5,
            )
        result = self.queue.complete_with_increment(
            task_id="task-1", worker_id="worker-b", lease_token=2,
            now=16, effect_key="effect-1", state_key="balance", amount=5,
        )
        self.assertEqual(result["value"], 5)

    def test_lease_renewal_cannot_revive_an_expired_lease(self):
        self.submit()
        claimed = self.claim()
        self.assertTrue(self.queue.renew_lease(
            task_id="task-1", worker_id="worker-a", lease_token=claimed["lease_token"],
            now=12, lease_seconds=20,
        ))
        self.assertFalse(self.queue.renew_lease(
            task_id="task-1", worker_id="worker-a", lease_token=claimed["lease_token"],
            now=40, lease_seconds=20,
        ))

    def test_cancel_is_terminal_and_prevents_claim(self):
        self.submit()
        self.assertTrue(self.queue.cancel("task-1"))
        self.assertEqual(self.queue.get_task("task-1")["status"], "cancelled")
        self.assertIsNone(self.claim())

    def test_local_effect_and_task_completion_are_one_transaction(self):
        self.submit()
        claimed = self.claim()
        with self.assertRaisesRegex(RuntimeError, "simulated_crash"):
            self.queue.complete_with_increment(
                task_id="task-1", worker_id="worker-a", lease_token=claimed["lease_token"],
                now=11, effect_key="effect-1", state_key="balance", amount=7,
                fail_after_effect=True,
            )
        self.assertEqual(self.queue.get_state("balance"), 0)
        self.assertIsNone(self.queue.get_effect("effect-1"))
        self.assertEqual(self.queue.get_task("task-1")["status"], "running")
        result = self.queue.complete_with_increment(
            task_id="task-1", worker_id="worker-a", lease_token=claimed["lease_token"],
            now=11, effect_key="effect-1", state_key="balance", amount=7,
        )
        self.assertEqual(result["value"], 7)
        self.assertEqual(self.queue.get_task("task-1")["status"], "completed")

    def test_effect_key_prevents_duplicate_local_increment(self):
        self.submit()
        first = self.claim()
        self.queue.complete_with_increment(
            task_id="task-1", worker_id="worker-a", lease_token=first["lease_token"],
            now=11, effect_key="payment-1", state_key="balance", amount=10,
        )
        self.submit(task_id="task-2", key="idem-2")
        second = self.claim(worker="worker-b", now=12)
        replay = self.queue.complete_with_increment(
            task_id="task-2", worker_id="worker-b", lease_token=second["lease_token"],
            now=13, effect_key="payment-1", state_key="balance", amount=10,
        )
        self.assertTrue(replay["effect_replayed"])
        self.assertEqual(self.queue.get_state("balance"), 10)

    def test_effect_key_with_different_payload_is_rejected(self):
        self.submit()
        first = self.claim()
        self.queue.complete_with_increment(
            task_id="task-1", worker_id="worker-a", lease_token=first["lease_token"],
            now=11, effect_key="effect-1", state_key="balance", amount=10,
        )
        self.submit(task_id="task-2", key="idem-2")
        second = self.claim(worker="worker-b", now=12)
        with self.assertRaises(IdempotencyConflict):
            self.queue.complete_with_increment(
                task_id="task-2", worker_id="worker-b", lease_token=second["lease_token"],
                now=13, effect_key="effect-1", state_key="balance", amount=11,
            )

    def test_task_and_effect_survive_process_reopen(self):
        self.submit()
        claimed = self.claim()
        self.queue.complete_with_increment(
            task_id="task-1", worker_id="worker-a", lease_token=claimed["lease_token"],
            now=11, effect_key="effect-1", state_key="balance", amount=4,
        )
        reopened = DurableQueue(self.path)
        self.assertEqual(reopened.get_task("task-1")["status"], "completed")
        self.assertEqual(reopened.get_state("balance"), 4)
        self.assertIsNotNone(reopened.get_effect("effect-1"))

    def test_deadline_expiry_is_terminal(self):
        self.submit(deadline=12)
        self.assertEqual(self.queue.expire_deadlines(now=12), 1)
        self.assertEqual(self.queue.get_task("task-1")["status"], "failed")
        self.assertEqual(self.queue.get_task("task-1")["error_code"], "deadline_exceeded")

    def test_retry_respects_backoff_and_attempt_budget(self):
        self.submit(max_attempts=2)
        first = self.claim(now=10)
        self.assertEqual(self.queue.retry(
            task_id="task-1", worker_id="worker-a", lease_token=first["lease_token"],
            now=11, delay_seconds=5,
        ), "queued")
        self.assertIsNone(self.claim(worker="worker-b", now=15))
        second = self.claim(worker="worker-b", now=16)
        self.assertEqual(second["attempts"], 2)
        self.assertEqual(self.queue.retry(
            task_id="task-1", worker_id="worker-b", lease_token=second["lease_token"],
            now=17, delay_seconds=1,
        ), "failed")

    def test_two_workers_cannot_claim_the_same_task(self):
        self.submit()
        barrier = threading.Barrier(3)
        results = []

        def worker(name):
            barrier.wait()
            results.append(self.queue.claim(worker_id=name, now=10, lease_seconds=10))

        threads = [
            threading.Thread(target=worker, args=("worker-a",)),
            threading.Thread(target=worker, args=("worker-b",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)



    def test_submission_rejects_boolean_and_non_integer_limits(self):
        with self.assertRaisesRegex(ValueError, "invalid_now"):
            self.queue.submit(
                task_id="task-1", idempotency_key="idem-1", payload={},
                now=True, deadline_at=100, max_attempts=3,
            )
        with self.assertRaisesRegex(ValueError, "invalid_max_attempts"):
            self.queue.submit(
                task_id="task-1", idempotency_key="idem-1", payload={},
                now=1, deadline_at=100, max_attempts=1.5,
            )

    def test_non_finite_or_non_object_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_task_payload"):
            self.submit(payload={"amount": float("nan")})
        with self.assertRaisesRegex(ValueError, "invalid_task_submission"):
            self.queue.submit(
                task_id="task-1", idempotency_key="idem-1", payload=[],
                now=10, deadline_at=100,
            )

    def test_boolean_amount_cannot_be_persisted_as_integer_effect(self):
        self.submit()
        claimed = self.claim()
        with self.assertRaisesRegex(ValueError, "invalid_amount"):
            self.queue.complete_with_increment(
                task_id="task-1", worker_id="worker-a",
                lease_token=claimed["lease_token"], now=11,
                effect_key="effect-1", state_key="balance", amount=True,
            )
        self.assertEqual(self.queue.get_state("balance"), 0)
        self.assertEqual(self.queue.get_task("task-1")["status"], "running")

    def test_boolean_lease_token_and_worker_identity_are_rejected(self):
        self.submit()
        with self.assertRaisesRegex(ValueError, "invalid_worker_id"):
            self.queue.claim(worker_id=" ", now=10, lease_seconds=5)
        claimed = self.claim()
        with self.assertRaisesRegex(ValueError, "invalid_lease_token"):
            self.queue.renew_lease(
                task_id="task-1", worker_id="worker-a", lease_token=True,
                now=11, lease_seconds=5,
            )


    def test_cancel_fences_worker_before_any_later_local_effect(self):
        self.submit()
        claimed = self.claim()
        self.assertTrue(self.queue.cancel("task-1"))
        with self.assertRaises(StaleLease):
            self.queue.complete_with_increment(
                task_id="task-1", worker_id="worker-a",
                lease_token=claimed["lease_token"], now=11,
                effect_key="effect-1", state_key="balance", amount=9,
            )
        self.assertEqual(self.queue.get_task("task-1")["status"], "cancelled")
        self.assertEqual(self.queue.get_state("balance"), 0)
        self.assertIsNone(self.queue.get_effect("effect-1"))

    def test_cancel_and_atomic_completion_have_one_serialized_winner(self):
        self.submit()
        claimed = self.claim()
        barrier = threading.Barrier(3)
        outcomes = {}

        def cancel():
            barrier.wait()
            outcomes["cancelled"] = self.queue.cancel("task-1")

        def complete():
            barrier.wait()
            try:
                self.queue.complete_with_increment(
                    task_id="task-1", worker_id="worker-a",
                    lease_token=claimed["lease_token"], now=11,
                    effect_key="effect-1", state_key="balance", amount=9,
                )
                outcomes["completion"] = "completed"
            except StaleLease:
                outcomes["completion"] = "fenced"

        threads = [threading.Thread(target=cancel), threading.Thread(target=complete)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        task = self.queue.get_task("task-1")
        if task["status"] == "completed":
            self.assertEqual(outcomes, {"cancelled": False, "completion": "completed"})
            self.assertEqual(self.queue.get_state("balance"), 9)
            self.assertIsNotNone(self.queue.get_effect("effect-1"))
        else:
            self.assertEqual(task["status"], "cancelled")
            self.assertEqual(outcomes, {"cancelled": True, "completion": "fenced"})
            self.assertEqual(self.queue.get_state("balance"), 0)
            self.assertIsNone(self.queue.get_effect("effect-1"))

if __name__ == "__main__":
    unittest.main()
