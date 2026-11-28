"""Adversarial conformance cases for the deterministic E-003 reference model."""
import unittest

from semantics import Engine


class ConcurrencyAdversarialTests(unittest.TestCase):
    def test_retry_rejoins_tail_instead_of_starving_older_queued_work(self):
        engine = Engine(max_outstanding=4, max_concurrency=1)
        engine.submit("retrying", "key-r", ttl=20, max_attempts=2)
        engine.submit("waiting", "key-w", ttl=20)
        self.assertEqual(engine.start("worker"), "retrying")
        self.assertEqual(engine.finish("worker", "transient"), "queued")
        self.assertEqual(engine.start("worker"), "waiting")
        self.assertEqual(engine.finish("worker", "ok"), "completed")
        self.assertEqual(engine.start("worker"), "retrying")

    def test_crashed_worker_requeues_behind_previously_admitted_work(self):
        engine = Engine(max_outstanding=4, max_concurrency=1)
        engine.submit("crashed", "key-c", ttl=20, max_attempts=2)
        engine.submit("older", "key-o", ttl=20)
        self.assertEqual(engine.start("worker"), "crashed")
        self.assertEqual(engine.crash("worker"), "queued")
        self.assertEqual(engine.start("worker"), "older")
        self.assertEqual(engine.finish("worker", "ok"), "completed")
        self.assertEqual(engine.start("worker"), "crashed")

    def test_backpressure_recovers_only_after_terminal_transition(self):
        engine = Engine(max_outstanding=1, max_concurrency=1)
        engine.submit("one", "key-one", ttl=10)
        self.assertEqual(engine.submit("two", "key-two", ttl=10).status, "backpressure")
        engine.start("worker")
        engine.cancel("one")
        self.assertEqual(engine.submit("two", "key-two", ttl=10).status, "backpressure")
        self.assertEqual(engine.finish("worker", "ok"), "cancelled")
        self.assertEqual(engine.submit("two", "key-two", ttl=10).status, "accepted")

    def test_duplicate_key_still_resolves_after_admission_closes(self):
        engine = Engine(max_outstanding=1, max_concurrency=1)
        original = engine.submit("one", "same-key", ttl=10)
        engine.shutdown(graceful=True)
        duplicate = engine.submit("different-id", "same-key", ttl=10)
        self.assertEqual(duplicate.status, "deduplicated")
        self.assertEqual(duplicate.task_id, original.task_id)

    def test_retry_never_resets_absolute_deadline(self):
        engine = Engine(max_outstanding=2, max_concurrency=1)
        engine.submit("one", "key-one", ttl=3, max_attempts=3)
        self.assertEqual(engine.start("worker"), "one")
        engine.advance(2)
        self.assertEqual(engine.finish("worker", "transient"), "queued")
        engine.advance(1)
        self.assertEqual(engine.tasks["one"].status, "expired")
        self.assertIsNone(engine.start("worker"))

    def test_cancellation_wins_over_late_worker_success(self):
        engine = Engine(max_outstanding=2, max_concurrency=1)
        engine.submit("one", "key-one", ttl=10)
        engine.start("worker")
        self.assertTrue(engine.cancel("one"))
        self.assertEqual(engine.finish("worker", "ok", result="must-not-publish"), "cancelled")
        self.assertIsNone(engine.tasks["one"].result)
        self.assertEqual(engine.completed_keys, set())

    def test_worker_crash_after_cancellation_acknowledges_stop_not_retry(self):
        engine = Engine(max_outstanding=2, max_concurrency=1)
        engine.submit("one", "key-one", ttl=10, max_attempts=4)
        engine.start("worker")
        engine.cancel("one")
        self.assertEqual(engine.crash("worker"), "cancelled")
        self.assertEqual(engine.tasks["one"].attempts, 1)
        self.assertTrue(engine.is_drained())


if __name__ == "__main__":
    unittest.main()
