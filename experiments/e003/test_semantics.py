import unittest

from semantics import Engine


class EngineSemanticsTests(unittest.TestCase):
    def engine(self, *, outstanding=3, concurrency=2):
        return Engine(max_outstanding=outstanding, max_concurrency=concurrency)

    def test_backpressure_is_explicit_and_does_not_enqueue(self):
        engine = self.engine(outstanding=1, concurrency=1)
        self.assertEqual(engine.submit("a", "key-a", ttl=5).status, "accepted")
        self.assertEqual(engine.submit("b", "key-b", ttl=5).status, "backpressure")
        self.assertNotIn("b", engine.tasks)

    def test_concurrency_is_bounded(self):
        engine = self.engine(outstanding=3, concurrency=1)
        engine.submit("a", "key-a", ttl=5)
        engine.submit("b", "key-b", ttl=5)
        self.assertEqual(engine.start("worker-1"), "a")
        self.assertIsNone(engine.start("worker-2"))
        self.assertEqual(len(engine.workers), 1)

    def test_transient_failure_retries_only_within_attempt_budget(self):
        engine = self.engine()
        engine.submit("a", "key-a", ttl=5, max_attempts=2)
        self.assertEqual(engine.start("w"), "a")
        self.assertEqual(engine.finish("w", "transient"), "queued")
        self.assertEqual(engine.start("w"), "a")
        self.assertEqual(engine.finish("w", "transient"), "failed")
        self.assertEqual(engine.tasks["a"].attempts, 2)

    def test_deadline_expires_queued_and_running_work(self):
        engine = self.engine()
        engine.submit("a", "key-a", ttl=2)
        engine.submit("b", "key-b", ttl=1)
        self.assertEqual(engine.start("w"), "a")
        engine.advance(1)
        self.assertEqual(engine.tasks["b"].status, "expired")
        engine.advance(1)
        self.assertEqual(engine.tasks["a"].status, "cancelling")
        self.assertEqual(engine.workers, {"w": "a"})
        self.assertEqual(engine.finish("w", "ok", result="late"), "expired")
        self.assertEqual(engine.workers, {})

    def test_cancellation_releases_worker_capacity(self):
        engine = self.engine(outstanding=2, concurrency=1)
        engine.submit("a", "key-a", ttl=5)
        engine.submit("b", "key-b", ttl=5)
        engine.start("w")
        self.assertTrue(engine.cancel("a"))
        self.assertEqual(engine.tasks["a"].status, "cancelling")
        self.assertIsNone(engine.start("worker-2"))
        self.assertEqual(engine.finish("w", "ok", result="late"), "cancelled")
        self.assertEqual(engine.start("w"), "b")
        self.assertEqual(engine.tasks["a"].status, "cancelled")

    def test_worker_crash_requeues_only_when_attempts_remain(self):
        engine = self.engine()
        engine.submit("a", "key-a", ttl=5, max_attempts=2)
        self.assertEqual(engine.start("w"), "a")
        self.assertEqual(engine.crash("w"), "queued")
        self.assertEqual(engine.start("w"), "a")
        self.assertEqual(engine.crash("w"), "failed")

    def test_idempotency_key_deduplicates_active_and_completed_work(self):
        engine = self.engine()
        first = engine.submit("a", "same-key", ttl=5)
        duplicate = engine.submit("b", "same-key", ttl=5)
        self.assertEqual(first.status, "accepted")
        self.assertEqual(duplicate.status, "deduplicated")
        self.assertEqual(first.task_id, duplicate.task_id)
        self.assertEqual(engine.start("w"), "a")
        engine.finish("w", "ok", result="stored")
        after_completion = engine.submit("c", "same-key", ttl=5)
        self.assertEqual(after_completion.status, "deduplicated")
        self.assertEqual(after_completion.task_id, "a")
        self.assertEqual(engine.tasks["a"].result, "stored")

    def test_completed_task_does_not_retry(self):
        engine = self.engine()
        engine.submit("a", "key-a", ttl=5, max_attempts=3)
        engine.start("w")
        self.assertEqual(engine.finish("w", "ok"), "completed")
        self.assertIsNone(engine.start("w"))

    def test_graceful_shutdown_rejects_new_work_and_drains_accepted_work(self):
        engine = self.engine()
        engine.submit("a", "key-a", ttl=5)
        self.assertFalse(engine.shutdown(graceful=True))
        rejected = engine.submit("b", "key-b", ttl=5)
        self.assertEqual(rejected.status, "shutting_down")
        self.assertEqual(engine.start("w"), "a")
        self.assertEqual(engine.finish("w", "ok"), "completed")
        self.assertTrue(engine.is_drained())

    def test_immediate_shutdown_cancels_queued_and_running_work(self):
        engine = self.engine(outstanding=3, concurrency=1)
        engine.submit("a", "key-a", ttl=5)
        engine.submit("b", "key-b", ttl=5)
        engine.start("w")
        self.assertFalse(engine.shutdown(graceful=False))
        self.assertEqual(engine.tasks["a"].status, "cancelling")
        self.assertEqual(engine.tasks["b"].status, "cancelled")
        self.assertEqual(engine.workers, {"w": "a"})
        self.assertEqual(engine.finish("w", "ok"), "cancelled")
        self.assertTrue(engine.is_drained())
        self.assertIsNone(engine.start("w"))



    def test_boolean_and_non_integer_limits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_max_outstanding"):
            Engine(max_outstanding=True, max_concurrency=1)
        with self.assertRaisesRegex(ValueError, "invalid_max_concurrency"):
            Engine(max_outstanding=2, max_concurrency=1.5)

    def test_submission_rejects_invalid_identity_and_limits(self):
        engine = self.engine()
        with self.assertRaisesRegex(ValueError, "invalid_task_id"):
            engine.submit([], "key", ttl=5)
        with self.assertRaisesRegex(ValueError, "invalid_idempotency_key"):
            engine.submit("task", " ", ttl=5)
        with self.assertRaisesRegex(ValueError, "invalid_ttl"):
            engine.submit("task", "key", ttl=True)

    def test_worker_and_time_inputs_reject_invalid_types(self):
        engine = self.engine()
        with self.assertRaisesRegex(ValueError, "invalid_worker_id"):
            engine.start(" ")
        with self.assertRaisesRegex(ValueError, "invalid_ticks"):
            engine.advance(True)
        with self.assertRaisesRegex(ValueError, "invalid_graceful_shutdown_flag"):
            engine.shutdown(graceful=1)

    def test_finish_rejects_non_string_result_and_unknown_outcome(self):
        engine = self.engine()
        engine.submit("a", "key-a", ttl=5)
        engine.start("worker")
        with self.assertRaisesRegex(ValueError, "invalid_result"):
            engine.finish("worker", "ok", result={"secret": "not a string"})
        with self.assertRaisesRegex(ValueError, "unsupported_outcome"):
            engine.finish("worker", ["ok"])

if __name__ == "__main__":
    unittest.main()
