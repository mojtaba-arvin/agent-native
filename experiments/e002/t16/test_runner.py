from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run import aggregate, markdown_report, parse_cpu_list, run_command, run_loadgen_container, verify_candidate_cgroup, verify_image_identity, unexpected_untracked_files


class T16RunnerUnitTests(unittest.TestCase):
    def test_untracked_evidence_is_scoped_to_t16_evidence_directory(self):
        untracked = [
            "experiments/e002/t16/evidence/previous/results.json",
            "experiments/e002/t16/evidence/current/prereg.json",
            "unexpected.txt",
        ]
        allowed = {"experiments/e002/t16/prereg.json"}
        self.assertEqual(unexpected_untracked_files(untracked, allowed), ["unexpected.txt"])

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

    def test_loadgen_container_is_cpu_memory_pinned_and_writes_to_evidence_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            output = root / "experiments/e002/t16"
            root.mkdir()
            output.mkdir(parents=True)
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
                    output, "read-secret", "deny-secret", "ghcr.io/example/t16@sha256:" + "a" * 64,
                )
            self.assertEqual(result["limits"]["cpuset_cpus_effective"], "3")
            verify.assert_called_once_with(cgroup, 3)
            docker_run = calls[0]
            self.assertIn("--cpus=1", docker_run)
            self.assertIn("--cpuset-cpus=3", docker_run)
            self.assertIn("--memory=1g", docker_run)
            self.assertIn(f"{output}:/evidence:rw", docker_run)
            self.assertIn("--entrypoint", docker_run)
            self.assertIn("/opt/candidates/t16-loadgen", docker_run)
            self.assertIn("ghcr.io/example/t16@sha256:" + "a" * 64, docker_run)
            self.assertIn("T16_READ_TOKEN=read-secret", docker_run)
            self.assertIn("T16_DENY_TOKEN=deny-secret", docker_run)
            self.assertEqual(calls[-1][:4], ["docker", "rm", "--force", "t16-loadgen-test"])

    def test_image_verifier_rejects_mutable_tag_before_docker_access(self):
        with mock.patch("run.run_command") as command:
            with self.assertRaisesRegex(ValueError, "immutable"):
                verify_image_identity("ghcr.io/example/t16:latest", "a" * 40)
            command.assert_not_called()

    def test_image_verifier_accepts_exact_digest_and_checks_attestation(self):
        image_ref = "ghcr.io/mojtaba-arvin/agent-native-t16@sha256:" + "b" * 64
        source_sha = "a" * 40
        with mock.patch("run.shutil.which", return_value="/usr/bin/gh"), mock.patch("run.run_command", side_effect=["", source_sha, "https://github.com/mojtaba-arvin/agent-native", json.dumps([image_ref]), "verified"]) as command:
            identity = verify_image_identity(image_ref, source_sha)
        self.assertEqual(identity["image_ref"], image_ref)
        self.assertEqual(identity["image_digest"], "sha256:" + "b" * 64)
        self.assertEqual(command.call_args_list[-1].args[0], [
            "gh", "attestation", "verify", "oci://" + image_ref,
            "-R", "mojtaba-arvin/agent-native",
        ])

    def test_command_runner_can_record_expected_failure_without_raising(self):
        import sys
        output = run_command([sys.executable, "-c", "raise SystemExit(7)"], allow_failure=True)
        self.assertEqual(output, "")
        with self.assertRaisesRegex(RuntimeError, "command failed"):
            run_command([sys.executable, "-c", "raise SystemExit(7)"])


if __name__ == "__main__":
    unittest.main()
