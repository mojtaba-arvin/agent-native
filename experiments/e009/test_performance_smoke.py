from __future__ import annotations

import unittest

from performance_smoke import evaluate_capacity_gate


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
