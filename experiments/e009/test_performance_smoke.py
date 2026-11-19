from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from performance_smoke import DEFAULT_CAPACITY_THRESHOLDS, evaluate_capacity_gate, load_preregistration_config


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

    def test_frozen_capacity_manifest_has_exact_parameters_and_blob_pin(self):
        manifest_path = Path(__file__).with_name("capacity-confirmation-v1.json")
        config, blob_sha1 = load_preregistration_config(manifest_path)
        self.assertEqual(config["cohort_id"], "E009-CAPACITY-CONFIRMATION-2026-11-19-V1")
        self.assertTrue(config["no_apply"])
        self.assertEqual(config["parameters"]["repetitions"], 10)
        self.assertEqual(config["parameters"]["audit_batch_delay_ms"], 1.0)
        self.assertEqual(config["thresholds"]["maximum_aggregate_p99_ms"], 100)
        self.assertRegex(blob_sha1, r"^[0-9a-f]{40}$")

    def test_capacity_gate_uses_supplied_preregistered_thresholds(self):
        thresholds = dict(DEFAULT_CAPACITY_THRESHOLDS)
        thresholds["minimum_throughput_requests_per_second"] = 101.0
        result = evaluate_capacity_gate(self.aggregate(), self.metrics(), thresholds)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["throughput_at_least_100_rps"])
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
        self.assertFalse(result["checks"]["aggregate_p99_at_most_100_ms"])

    def test_missing_or_unlimited_cgroup_accounting_fails_closed(self):
        metrics = self.metrics()
        metrics["server_containerized"] = False
        metrics["server_cpu_quota_cores"] = None
        metrics["server_peak_cgroup_memory_bytes"] = None
        metrics["cgroup_v2_limits"] = None
        result = evaluate_capacity_gate(self.aggregate(), metrics)
        self.assertFalse(result["passed"])
        self.assertFalse(result["checks"]["server_cgroup_is_one_cpu"])
        self.assertFalse(result["checks"]["peak_cgroup_memory_at_most_1_gib"])


if __name__ == "__main__":
    unittest.main()
