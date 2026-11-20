from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import aggregate, markdown_report, parse_cpu_list, run_command, verify_candidate_cgroup


class T16RunnerUnitTests(unittest.TestCase):
    def test_cpu_set_parser_handles_ranges_and_disjoint_sets(self):
        self.assertEqual(parse_cpu_list("0-2,4,6-7"), [0, 1, 2, 4, 6, 7])
        self.assertEqual(parse_cpu_list("3"), [3])

    def test_candidate_cgroup_verifier_requires_exact_one_cpu_and_one_gib(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cpu.max").write_text("100000 100000")
            (root / "cpuset.cpus.effective").write_text("4")
            (root / "memory.max").write_text("1073741824")
            evidence = verify_candidate_cgroup(root, 4)
            self.assertEqual(evidence["memory_max_bytes"], 1073741824)
            (root / "memory.max").write_text("2147483648")
            with self.assertRaisesRegex(RuntimeError, "memory limit mismatch"):
                verify_candidate_cgroup(root, 4)

    def test_cohort_aggregate_counts_all_ten_run_metrics(self):
        records = [
            {
                "candidate": "go-net-http",
                "slo_pass": True,
                "metrics": {
                    "completed_requests_per_second": 101.0,
                    "p99_ms": 40.0,
                    "cpu_seconds": 12.0,
                    "memory_peak_bytes": 500000000,
                },
            }
            for _ in range(10)
        ]
        result = aggregate(records, "go-net-http")
        self.assertEqual(result["runs"], 10)
        self.assertEqual(result["slo_passed_runs"], 10)
        self.assertEqual(result["throughput_mean_rps"], 101.0)
        self.assertEqual(result["memory_peak_max_bytes"], 500000000)

    def test_report_contains_each_run_identifier(self):
        record = {
            "candidate": "go-net-http", "run_id": "t16-go-net-http-rep-01",
            "metrics": {
                "completed_requests_per_second": 100.0, "p99_ms": 90.0,
                "cpu_seconds": 20.0, "memory_peak_bytes": 900000000,
                "oom_events": 0, "security_or_integrity_violations": 0,
            },
            "slo_pass": True,
        }
        rust_record = {**record, "candidate": "rust-tokio-hyper", "run_id": "t16-rust-tokio-hyper-rep-01"}
        report = markdown_report("a" * 40, "b" * 64, [record, rust_record], {
            "cpu_model": "test CPU", "machine": "x86_64",
            "kernel_release": "test-kernel", "postgres_version": "16.4",
            "physical_host_isolation": "dedicated",
        })
        self.assertIn(record["run_id"], report)

    def test_command_runner_can_record_expected_failure_without_raising(self):
        import sys
        output = run_command([sys.executable, "-c", "raise SystemExit(7)"], allow_failure=True)
        self.assertEqual(output, "")
        with self.assertRaisesRegex(RuntimeError, "command failed"):
            run_command([sys.executable, "-c", "raise SystemExit(7)"])


if __name__ == "__main__":
    unittest.main()
