"""Reproducibility checks for the E-003 logical scheduling trace."""
import unittest

from performance_trace import run_trace


class PerformanceTraceTests(unittest.TestCase):
    def test_trace_is_deterministic_and_reports_queueing_not_wall_time(self):
        first = run_trace(task_count=16, concurrency=4)
        second = run_trace(task_count=16, concurrency=4)
        self.assertEqual(first, second)
        self.assertTrue(first["reference_only"])
        self.assertEqual(first["measurement"], "logical_ticks_not_wall_clock")
        self.assertEqual(first["result"], {
            "accepted": 16,
            "completed": 16,
            "attempts": 16,
            "max_observed_concurrency": 4,
            "logical_duration_ticks": 4,
            "queue_wait_ticks_p50": 1,
            "queue_wait_ticks_p99": 3,
        })
        self.assertEqual(len(first["events"]), 48)

    def test_trace_rejects_invalid_workload_bounds(self):
        with self.assertRaisesRegex(ValueError, "invalid_task_count"):
            run_trace(task_count=True)
        with self.assertRaisesRegex(ValueError, "invalid_concurrency"):
            run_trace(task_count=4, concurrency=0)


if __name__ == "__main__":
    unittest.main()
