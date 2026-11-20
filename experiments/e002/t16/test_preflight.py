from __future__ import annotations

import hashlib
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from preflight import (  # noqa: E402
    REQUEST_MIX,
    THRESHOLDS,
    build_preregistration,
    build_protocol,
    canonical_json,
    validate_attestation,
)


class T16PreflightTests(unittest.TestCase):
    def test_preregistration_is_bound_to_source_and_has_required_protocol(self):
        source = "a" * 40
        prereg = build_preregistration(
            source, ["python3", "run_t16.py"],
            datetime(2026, 11, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(prereg["task"], "T16")
        self.assertEqual(prereg["source_sha"], source)
        self.assertEqual(prereg["repetitions_per_candidate"], 10)
        self.assertEqual(prereg["requests_per_repetition"], 5000)
        self.assertEqual(prereg["concurrency"], 32)
        self.assertEqual(prereg["warmup_requests"], 250)
        self.assertEqual(prereg["target_completed_rps"], 100)
        self.assertEqual(prereg["thresholds"], THRESHOLDS)
        self.assertEqual(prereg["sha256"], hashlib.sha256(
            canonical_json({k: v for k, v in prereg.items() if k != "sha256"})
        ).hexdigest())

    def test_invalid_or_short_source_sha_is_rejected(self):
        for value in ("", "a" * 39, "g" * 40):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "source_sha"):
                    build_preregistration(value, ["run"])

    def test_empty_benchmark_command_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "command"):
            build_preregistration("a" * 40, [])

    def test_protocol_encodes_exact_product_mix_and_postgres(self):
        protocol = build_protocol("b" * 40, "16.4")
        self.assertEqual(protocol["request_mix"], REQUEST_MIX)
        self.assertEqual(sum(protocol["request_mix"].values()), 100)
        self.assertEqual(protocol["storage_engine"], "PostgreSQL")
        self.assertEqual(protocol["postgres_version"], "16.4")
        self.assertEqual(protocol["arrival_model"], "open_loop")
        self.assertEqual(protocol["arrival_schedule"], "fixed_rate_100_rps")
        self.assertIn("keep-alive", protocol["connection_policy"])
        self.assertEqual(protocol["trace_timing_fields"], ["scheduled_offset_ms", "offered_at", "started_at", "finished_at"])
        self.assertEqual(protocol["cpu_max"], "100000 100000")
        self.assertEqual(protocol["memory_max_bytes"], 1073741824)

    def test_host_attestation_requires_explicit_dedicated_host_claim(self):
        good = {
            "dedicated_physical_host": True,
            "host_id": "lab-host-01",
            "attested_by": "operator",
            "attested_at": "2026-11-20T10:00:00Z",
        }
        self.assertEqual(validate_attestation(good)["host_id"], "lab-host-01")
        for bad in (
            {},
            {**good, "dedicated_physical_host": False},
            {**good, "attested_by": ""},
            {**good, "attested_at": "2026-11-20T10:00:00"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_attestation(bad)


if __name__ == "__main__":
    unittest.main()
