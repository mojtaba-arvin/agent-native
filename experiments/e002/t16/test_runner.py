from __future__ import annotations

import sys
import tempfile
import unittest
import hashlib
import json
import tarfile
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import aggregate, markdown_report, parse_cpu_list, run_command, run_loadgen_container, verify_candidate_cgroup, write_evidence_bundle


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

    def test_failed_attempt_without_metrics_is_preserved_in_partial_report(self):
        failed = {
            "candidate": "go-net-http",
            "run_id": "t16-go-net-http-rep-01",
            "status": "failed",
            "functional_conformance": False,
            "slo_pass": False,
            "error": "RuntimeError: candidate did not become ready",
        }
        cohort = aggregate([failed], "go-net-http")
        self.assertEqual(cohort["attempts"], 1)
        self.assertEqual(cohort["runs"], 0)
        report = markdown_report("a" * 40, "b" * 64, [failed], {
            "cpu_model": "test CPU", "machine": "x86_64",
            "kernel_release": "test-kernel", "postgres_version": "16.4",
            "physical_host_isolation": "dedicated",
        })
        self.assertIn(failed["run_id"], report)
        self.assertIn("attempt error", report)

    def test_failed_attempt_with_partial_metrics_is_aggregated_but_not_passed(self):
        failed = {
            "candidate": "rust-tokio-hyper",
            "run_id": "t16-rust-tokio-hyper-rep-01",
            "status": "failed",
            "slo_pass": False,
            "metrics": {
                "completed_requests_per_second": 0.0,
                "p99_ms": 0.0,
                "cpu_seconds": 0.0,
                "memory_peak_bytes": 0,
            },
        }
        cohort = aggregate([failed], "rust-tokio-hyper")
        self.assertEqual(cohort["attempts"], 1)
        self.assertEqual(cohort["runs"], 1)
        self.assertEqual(cohort["slo_passed_runs"], 0)

    def test_evidence_bundle_contains_hashed_raw_outputs_but_not_build_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence"
            runs = output / "runs" / "go-net-http"
            binary = output / "bin"
            runs.mkdir(parents=True)
            binary.mkdir()
            for name in ("prereg.json", "host.json", "protocol.json", "ledger.jsonl", "results.json", "report.md"):
                (output / name).write_text(name, encoding="utf-8")
            (runs / "rep-01.jsonl").write_text('{"request_id":"one"}\n', encoding="utf-8")
            (binary / "t16-loadgen").write_text("not evidence", encoding="utf-8")
            archive_path = write_evidence_bundle(output, "a" * 40, "b" * 64)
            self.assertTrue(archive_path.is_file())
            manifest = json.loads((output / "evidence-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_sha"], "a" * 40)
            self.assertEqual(manifest["prereg_hash"], "b" * 64)
            raw = runs / "rep-01.jsonl"
            self.assertEqual(manifest["files"]["runs/go-net-http/rep-01.jsonl"], hashlib.sha256(raw.read_bytes()).hexdigest())
            with tarfile.open(archive_path, "r:gz") as archive:
                names = set(archive.getnames())
            self.assertIn("evidence-manifest.json", names)
            self.assertIn("runs/go-net-http/rep-01.jsonl", names)
            self.assertNotIn("bin/t16-loadgen", names)

    def test_loadgen_container_is_cpu_memory_pinned_and_writes_to_evidence_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            output = root / "experiments/e002/t16"
            binary = output / "bin"
            root.mkdir()
            output.mkdir(parents=True)
            binary.mkdir()
            cgroup = Path(directory) / "cgroup"
            cgroup.mkdir()
            calls = []
            def command(args, **kwargs):
                calls.append(args)
                if args[:2] == ["docker", "wait"]:
                    return "0"
                if args[:2] == ["docker", "logs"]:
                    return "loadgen summary"
                return ""
            with mock.patch("run.run_command", side_effect=command), \
                 mock.patch("run.container_cgroup", return_value=cgroup), \
                 mock.patch("run.verify_candidate_cgroup", return_value={
                     "cpu_max": "100000 100000", "cpuset_cpus_effective": "3",
                     "memory_max_bytes": 1073741824,
                 }) as verify:
                result = run_loadgen_container(
                    "t16-loadgen-test", ["--requests", "10"], 3,
                    root, binary, output, "read-secret", "deny-secret",
                )
            self.assertEqual(result["limits"]["cpuset_cpus_effective"], "3")
            verify.assert_called_once_with(cgroup, 3)
            docker_run = calls[0]
            self.assertIn("--cpus=1", docker_run)
            self.assertIn("--cpuset-cpus=3", docker_run)
            self.assertIn("--memory=1g", docker_run)
            self.assertIn(f"{output}:/evidence:rw", docker_run)
            self.assertIn(f"{root}:/src:ro", docker_run)
            self.assertIn("T16_READ_TOKEN=read-secret", docker_run)
            self.assertIn("T16_DENY_TOKEN=deny-secret", docker_run)
            self.assertEqual(calls[-1][:4], ["docker", "rm", "--force", "t16-loadgen-test"])

    def test_command_runner_can_record_expected_failure_without_raising(self):
        import sys
        output = run_command([sys.executable, "-c", "raise SystemExit(7)"], allow_failure=True)
        self.assertEqual(output, "")
        with self.assertRaisesRegex(RuntimeError, "command failed"):
            run_command([sys.executable, "-c", "raise SystemExit(7)"])


if __name__ == "__main__":
    unittest.main()
