import tempfile
import unittest
from pathlib import Path

from benchmark import (
    ProcessTreeCpuTracker,
    parse_proc_stat,
    proc_tree_sample,
    valid_measurement_response,
)


def write_process(root: Path, pid: int, *, comm: str, start_ticks: int, user_ticks: int, system_ticks: int, rss_kib: int, children: tuple[int, ...] = ()) -> None:
    process = root / str(pid)
    task = process / "task" / str(pid)
    task.mkdir(parents=True)
    # proc stat fields 3..22: state, then fields 4..22. The command name
    # deliberately contains spaces in one test; the parser must use the final ')'.
    fields = ["S"] + ["0"] * 19
    fields[11] = str(user_ticks)
    fields[12] = str(system_ticks)
    fields[19] = str(start_ticks)
    (process / "stat").write_text(
        f"{pid} ({comm}) " + " ".join(fields),
        encoding="utf-8",
    )
    (process / "status").write_text(f"Name:\t{comm}\nVmRSS:\t{rss_kib} kB\n", encoding="utf-8")
    (task / "children").write_text(" ".join(str(item) for item in children), encoding="ascii")


class BenchmarkResponseGateTests(unittest.TestCase):
    def test_only_expected_success_responses_are_counted_as_valid(self):
        self.assertTrue(valid_measurement_response({
            "status": 200, "body": "completed:0", "error": None
        }))

    def test_http_errors_wrong_bodies_and_transport_failures_are_rejected(self):
        invalid = [
            {"status": 500, "body": "completed:0", "error": None},
            {"status": 200, "body": "wrong", "error": None},
            {"status": None, "body": "", "error": "TimeoutError()"},
            {"status": 200, "body": "completed:0"},
        ]
        for item in invalid:
            with self.subTest(item=item):
                self.assertFalse(valid_measurement_response(item))


class ProcessTreeAccountingTests(unittest.TestCase):
    def test_proc_stat_parser_handles_spaces_and_parentheses_in_command_name(self):
        fields = ["S"] + ["0"] * 19
        fields[11] = "10"
        fields[12] = "5"
        fields[19] = "777"
        raw = "123 (worker (pool) process) " + " ".join(fields)
        cpu_seconds, start_ticks = parse_proc_stat(raw, clock_ticks=100)
        self.assertEqual(cpu_seconds, 0.15)
        self.assertEqual(start_ticks, 777)

    def test_tree_sample_discovers_children_and_uses_pid_start_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_process(
                root, 100, comm="agent parent", start_ticks=1000,
                user_ticks=20, system_ticks=5, rss_kib=10, children=(101,),
            )
            write_process(
                root, 101, comm="worker child", start_ticks=2000,
                user_ticks=30, system_ticks=10, rss_kib=20,
            )
            snapshot = proc_tree_sample(100, proc_root=root, clock_ticks=100)
            self.assertEqual(set(snapshot), {(100, 1000), (101, 2000)})
            self.assertEqual(snapshot[(100, 1000)], (0.25, 10 * 1024))
            self.assertEqual(snapshot[(101, 2000)], (0.4, 20 * 1024))

    def test_accumulator_retains_exited_children_and_never_double_counts_samples(self):
        tracker = ProcessTreeCpuTracker()
        tracker.observe({
            (100, 1000): (0.2, 1024),
            (101, 2000): (0.5, 2048),
        })
        # Child 101 has exited; its last observed cumulative CPU remains included.
        tracker.observe({(100, 1000): (0.3, 1024)})
        self.assertAlmostEqual(tracker.total_cpu_seconds, 0.8)
        self.assertEqual(tracker.peak_tree_rss_bytes, 3072)

        # PID 101 is later reused by a different process; start time keeps
        # the identities separate rather than overwriting the exited process.
        tracker.observe({(101, 9000): (0.1, 512)})
        self.assertAlmostEqual(tracker.total_cpu_seconds, 0.9)
        self.assertEqual(tracker.peak_tree_rss_bytes, 3072)


if __name__ == "__main__":
    unittest.main()
