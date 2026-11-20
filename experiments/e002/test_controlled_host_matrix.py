from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from controlled_host_matrix import cpu_quota_cores, distribution, parse_cpu_list, parse_cpu_stat, unified_cgroup_path, write_json


class TestParseCPUStat(unittest.TestCase):
    def test_parse_cpu_stat(self):
        parsed = parse_cpu_stat(
            "usage_usec 1234\nuser_usec 1000\nsystem_usec 234\nnr_periods 10\nnr_throttled 2\nthrottled_usec 99\n"
        )
        self.assertEqual(parsed["usage_usec"], 1234)
        self.assertEqual(parsed["nr_throttled"], 2)

    def test_cpu_stat_requires_usage_accounting(self):
        with self.assertRaisesRegex(ValueError, "usage_usec"):
            parse_cpu_stat("nr_periods 10\n")

    def test_unified_cgroup_membership_is_required(self):
        self.assertEqual(
            unified_cgroup_path("0::/system.slice/docker-example.scope\n"),
            "/system.slice/docker-example.scope",
        )
        with self.assertRaisesRegex(ValueError, "unique cgroup-v2"):
            unified_cgroup_path("2:cpu:/legacy\n")


class TestOneVcpuQuota(unittest.TestCase):
    def test_one_vcpu_quota(self):
        self.assertEqual(cpu_quota_cores("100000 100000"), 1.0)
        self.assertEqual(cpu_quota_cores("200000 100000"), 2.0)
        self.assertIsNone(cpu_quota_cores("max 100000"))

    def test_invalid_cpu_quota_fails_closed(self):
        for value in ("100000", "0 100000", "100000 0", "abc 100000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cpu_quota_cores(value)


class TestAllowedCPUList(unittest.TestCase):
    def test_parse_cpu_list_ranges_and_singletons(self):
        self.assertEqual(parse_cpu_list("0-2,4,7-8"), [0, 1, 2, 4, 7, 8])
        self.assertEqual(parse_cpu_list("3"), [3])

    def test_invalid_cpu_list_fails(self):
        for value in ("2-1", "-1", "a", "1-"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_cpu_list(value)


class TestWriteJSON(unittest.TestCase):
    def test_write_json_produces_valid_document_and_one_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "protocol.json"
            write_json(path, {"cgroup": {"cpu.max": "100000 100000"}, "runs": 10})
            raw = path.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertFalse(raw.endswith(b"\\n"))
            self.assertEqual(json.loads(raw), {"cgroup": {"cpu.max": "100000 100000"}, "runs": 10})


class TestDistribution(unittest.TestCase):
    def test_descriptive_statistics(self):
        result = distribution([1.0, 2.0, 3.0, 4.0])
        self.assertEqual(result["mean"], 2.5)
        self.assertEqual(result["median"], 2.5)
        self.assertEqual(result["n"], 4)
        self.assertAlmostEqual(result["sample_stddev"], 1.2909944487358056)

    def test_empty_measurements_are_missing_not_zero(self):
        result = distribution([])
        self.assertIsNone(result["mean"])
        self.assertIsNone(result["median"])
        self.assertEqual(result["n"], 0)


if __name__ == "__main__":
    unittest.main()
