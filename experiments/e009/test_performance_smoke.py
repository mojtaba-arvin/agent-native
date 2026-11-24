from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from performance_smoke import (
    DEFAULT_CAPACITY_THRESHOLDS, build_run_manifest, evaluate_capacity_gate,
    load_preregistration_config, write_request_trace,
)


class E009CapacityGateTests(unittest.TestCase):
    def metrics(self):
        return {
            "server_containerized": True,
            "server_cpu_quota_cores": 1.0,
            "server_cpu_percent_of_one_core_during_load": 21.7,
            "server_peak_cgroup_memory_bytes": 36_888_576,
            "cgroup_v2_limits": {
                "cpu_max": "100000 100000",
                "memory_max": "1073741824",
            },
        }

    def aggregate(self):
        return {
            "throughput_requests_per_second": 100.04,
            "latency_ms": {"p99": 6.54},
            "failed_expectations": 0,
        }

    def test_manual_workflow_uses_only_the_frozen_capacity_manifest(self):
        repository_root = Path(__file__).resolve().parents[2]
        workflow = (repository_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        section = workflow.split("  performance-confirmation:", 1)[1].split("\n  models:", 1)[0]
        self.assertIn("Validate frozen preregistration and decision chain", section)
        self.assertIn("python scripts/check_preregistrations.py", section)
        self.assertIn("--config experiments/e009/capacity-confirmation-v1.json", section)
        self.assertIn('--trace-output "$RUNNER_TEMP/e009-requests.jsonl"', section)
        self.assertIn('--manifest-output "$RUNNER_TEMP/e009-run-manifest.json"', section)
        self.assertIn("${{ runner.temp }}/e009-requests.jsonl", section)
        self.assertIn("${{ runner.temp }}/e009-run-manifest.json", section)
        self.assertLess(
            section.index("python scripts/check_preregistrations.py"),
            section.index("python experiments/e009/performance_smoke.py"),
        )
        self.assertNotIn("--requests", section)
        self.assertNotIn("--repetitions", section)

    def test_frozen_capacity_manifest_has_exact_parameters_and_blob_pin(self):
        manifest_path = Path(__file__).with_name("capacity-confirmation-v1.json")
        config, blob_sha1 = load_preregistration_config(manifest_path)
        self.assertEqual(config["cohort_id"], "E009-CAPACITY-CONFIRMATION-2026-11-19-V1")
        self.assertTrue(config["no_apply"])
        self.assertEqual(config["parameters"]["repetitions"], 10)
        self.assertEqual(config["parameters"]["audit_batch_delay_ms"], 1.0)
        self.assertEqual(config["thresholds"]["maximum_aggregate_p99_ms"], 100)
        self.assertRegex(blob_sha1, r"^[0-9a-f]{40}$")

    def test_request_trace_is_complete_deterministic_jsonl_with_digest(self):
        records = [
            {"repetition": 2, "request_index": 1, "kind": "job_admission", "ok": True},
            {"repetition": 1, "request_index": 2, "kind": "expected_denial", "ok": True},
            {"repetition": 1, "request_index": 1, "kind": "authorized_read", "ok": True},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "requests.jsonl"
            digest = write_request_trace(path, records)
            raw = path.read_bytes()
            lines = raw.decode("utf-8").splitlines()
            self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        decoded = [json.loads(line) for line in lines]
        self.assertEqual(
            [(item["repetition"], item["request_index"]) for item in decoded],
            [(1, 1), (1, 2), (2, 1)],
        )
        self.assertEqual(len(decoded), len(records))

    def test_run_manifest_pins_source_parameters_preregistration_and_trace(self):
        args = SimpleNamespace(
            requests=5000, repetitions=10, concurrency=32, target_rps=100.0,
            containerized=True, enforce_capacity_gate=True, audit_batch_delay_ms=1.0,
            job_batch_size=32, job_batch_delay_ms=0.5, config=Path("capacity.json"),
            output=Path("summary.json"),
        )
        preregistration = {"cohort_id": "E009-COHORT", "thresholds": DEFAULT_CAPACITY_THRESHOLDS}
        manifest = build_run_manifest(
            run_id="run-123",
            started_at_utc="2026-11-23T10:00:00+00:00",
            finished_at_utc="2026-11-23T10:05:00+00:00",
            source={"revision": "a" * 40, "working_tree_clean": True, "sha256": {}},
            args=args,
            trace_path=Path("requests.jsonl"),
            trace_sha256="b" * 64,
            trace_count=50000,
            preregistration=preregistration,
            preregistration_sha1="c" * 40,
        )
        self.assertEqual(manifest["source"]["revision"], "a" * 40)
        self.assertEqual(manifest["parameters"]["repetitions"], 10)
        self.assertEqual(manifest["preregistration"]["git_blob_sha1"], "c" * 40)
        self.assertEqual(manifest["preregistration"]["thresholds"], DEFAULT_CAPACITY_THRESHOLDS)
        self.assertEqual(manifest["workload"]["seed"], 20261122)
        self.assertEqual(manifest["runtime"]["machine"], __import__("platform").machine())
        self.assertEqual(manifest["request_trace"]["records"], 50000)
        self.assertEqual(manifest["request_trace"]["sha256"], "b" * 64)
        json.dumps(manifest)

    def test_capacity_gate_uses_supplied_preregistered_thresholds(self):
        thresholds = dict(DEFAULT_CAPACITY_THRESHOLDS)
        thresholds["minimum_throughput_requests_per_second"] = 101.0
        result = evaluate_capacity_gate(self.aggregate(), self.metrics(), thresholds)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["throughput_meets_preregistered_minimum"])
        self.assertEqual(result["thresholds"]["minimum_throughput_requests_per_second"], 101.0)

    def test_rejects_capacity_manifest_that_allows_apply(self):
        manifest_path = Path(__file__).with_name("capacity-confirmation-v1.json")
        config = json.loads(manifest_path.read_text(encoding="utf-8"))
        config["no_apply"] = False
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no-apply"):
                load_preregistration_config(path)

    def test_measured_product_path_passes_all_preregistered_limits(self):
        result = evaluate_capacity_gate(self.aggregate(), self.metrics())
        self.assertTrue(result["passed"])
        self.assertTrue(all(result["checks"].values()))

    def test_tail_latency_regression_fails_gate(self):
        aggregate = self.aggregate()
        aggregate["latency_ms"]["p99"] = 100.01
        result = evaluate_capacity_gate(aggregate, self.metrics())
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["aggregate_p99_within_preregistered_maximum"])

    def test_missing_or_unlimited_cgroup_accounting_fails_closed(self):
        metrics = self.metrics()
        metrics["server_containerized"] = False
        metrics["server_cpu_quota_cores"] = None
        metrics["server_peak_cgroup_memory_bytes"] = None
        metrics["cgroup_v2_limits"] = None
        result = evaluate_capacity_gate(self.aggregate(), metrics)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["server_cgroup_matches_preregistered_cpu_quota"])
        self.assertFalse(result["checks"]["peak_cgroup_memory_within_preregistered_maximum"])


if __name__ == "__main__":
    unittest.main()
