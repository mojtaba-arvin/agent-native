from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ollama_diagnostics


class OllamaDiagnosticsTests(unittest.TestCase):
    def test_prefill_curve_preserves_prefix_and_measures_warm_cache(self):
        responses = [
            {
                "prompt_eval_count": count,
                "prompt_eval_cached_count": cached,
                "prompt_eval_duration": 1_000_000_000,
                "load_duration": 0,
                "eval_count": 1,
                "eval_duration": 10_000_000,
                "done_reason": "length",
            }
            for count, cached in (
                (1001, 0), (1001, 1001),
                (2001, 1001), (2001, 2001),
                (4001, 2001), (4001, 4001),
                (8001, 4001), (8001, 8001),
            )
        ]
        requests = []

        def fake_post(url, payload, timeout=600.0, deadline=None):
            requests.append(payload)
            return responses.pop(0)

        with patch.object(ollama_diagnostics, "post_json", side_effect=fake_post):
            observations = ollama_diagnostics.benchmark_prefill(
                "http://127.0.0.1:11434", "qwen3:8b", [2]
            )

        self.assertEqual(len(observations), 8)
        self.assertEqual(len(requests), 8)
        self.assertEqual(observations[0]["load_duration_ns"], 0)
        self.assertEqual(observations[0]["prompt_eval_duration_ns"], 1_000_000_000)
        self.assertEqual(observations[0]["prefill_duration_seconds"], 1.0)
        self.assertEqual(
            [item["target_words"] for item in observations],
            [1000, 1000, 2000, 2000, 4000, 4000, 8000, 8000],
        )
        self.assertEqual(
            [item["phase"] for item in observations],
            ["growth_or_cold", "exact_warm_repeat"] * 4,
        )
        self.assertEqual(
            [item["prompt_eval_cached_count"] for item in observations],
            [0, 1001, 1001, 2001, 2001, 4001, 4001, 8001],
        )
        self.assertTrue(all(item["keep_alive"] == "10m" for item in requests))
        self.assertTrue(all(item["options"]["num_thread"] == 2 for item in requests))
        self.assertEqual(requests[0]["prompt"], requests[1]["prompt"])
        self.assertTrue(requests[2]["prompt"].startswith(requests[0]["prompt"]))

    def test_prefill_checkpoint_is_updated_after_each_observation(self):
        responses = [
            {
                "prompt_eval_count": 10,
                "prompt_eval_cached_count": 0 if index % 2 == 0 else 10,
                "prompt_eval_duration": 1_000_000_000,
                "load_duration": 0,
                "eval_count": 1,
                "eval_duration": 10_000_000,
            }
            for index in range(8)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "partial.json"
            with patch.object(ollama_diagnostics, "post_json", side_effect=responses):
                observations = ollama_diagnostics.benchmark_prefill(
                    "http://127.0.0.1:11434", "qwen3:8b", [2], checkpoint
                )
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        self.assertEqual(len(observations), 8)
        self.assertEqual(saved["status"], "prefill_completed")
        self.assertEqual(saved["completed_observations"], 8)
        self.assertEqual(saved["expected_observations"], 8)
        self.assertEqual(len(saved["observations"]), 8)
        self.assertFalse(checkpoint.with_suffix(".json.tmp").exists())

    def test_short_schema_probe_includes_the_live_upfront_surface(self):
        surface = {
            "dispatch": {"name": "agent.invoke", "input_schema": {"type": "object"}},
            "tools": [
                {
                    "name": "service.inspect",
                    "input_schema": {
                        "type": "object",
                        "required": ["service_id"],
                        "properties": {"service_id": {"type": "string"}},
                    },
                }
            ],
        }
        messages = ollama_diagnostics.build_schema_probe_messages(surface)
        encoded_surface = messages[2]["content"]
        self.assertIn('"service.inspect"', encoded_surface)
        self.assertIn('"required": ["service_id"]', encoded_surface)
        self.assertIn("upfront disclosure arm", messages[0]["content"])
        self.assertEqual(messages[1]["content"], "Inspect the Catalog service using service.inspect.")

    def test_gateway_surface_read_has_an_independent_hard_timeout(self):
        read_fd, write_fd = os.pipe()
        stdout = os.fdopen(read_fd, "rb", buffering=0)

        class FakeProcess:
            def __init__(self):
                self.stdout = stdout
                self.stdin = None
                self.stderr = None
                self.killed = False
            def kill(self):
                self.killed = True
            def wait(self, timeout=None):
                return 0

        process = FakeProcess()
        try:
            with patch.object(ollama_diagnostics.subprocess, "Popen", return_value=process):
                with self.assertRaisesRegex(TimeoutError, "gateway_surface_timeout"):
                    ollama_diagnostics.read_gateway_surface(timeout=0.01)
            self.assertTrue(process.killed)
        finally:
            stdout.close()
            os.close(write_fd)

    def test_gateway_surface_read_returns_one_complete_session_line(self):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b'{"type":"session","surface":{}}\n')
        stdout = os.fdopen(read_fd, "rb", buffering=0)

        class FakeProcess:
            def __init__(self):
                self.stdout = stdout
                self.stdin = None
                self.stderr = None
            def kill(self):
                raise AssertionError("successful gateway process must not be killed")
            def wait(self, timeout=None):
                return 0

        try:
            with patch.object(ollama_diagnostics.subprocess, "Popen", return_value=FakeProcess()):
                process, session = ollama_diagnostics.read_gateway_surface(timeout=1.0)
            self.assertEqual(session, {"type": "session", "surface": {}})
        finally:
            stdout.close()
            os.close(write_fd)

    def test_phase_one_is_exactly_eight_observations_and_hashes_each_payload(self):
        responses = [{"prompt_eval_count": 100, "prompt_eval_cached_count": 0,
            "prompt_eval_duration": 1_000_000_000, "load_duration": 0,
            "eval_count": 1, "eval_duration": 10_000_000} for _ in range(8)]
        with patch.object(ollama_diagnostics, "post_json", side_effect=responses):
            observations = ollama_diagnostics.benchmark_prefill(
                "http://127.0.0.1:11434", "qwen3:8b", [2, 4], word_sizes=[1000, 4000])
        self.assertEqual(len(observations), 8)
        self.assertEqual([(x["target_words"], x["num_threads_requested"], x["phase"]) for x in observations], [
            (1000, 2, "growth_or_cold"), (1000, 2, "exact_warm_repeat"),
            (4000, 2, "growth_or_cold"), (4000, 2, "exact_warm_repeat"),
            (1000, 4, "growth_or_cold"), (1000, 4, "exact_warm_repeat"),
            (4000, 4, "growth_or_cold"), (4000, 4, "exact_warm_repeat")])
        for row in observations:
            self.assertEqual(len(row["payload_sha256"]), 64)
            self.assertEqual(len(row["prompt_sha256"]), 64)
            self.assertEqual(row["keep_alive"], "10m")
            self.assertEqual(row["payload_metadata"]["num_ctx"], 16384)

    def test_missing_cache_telemetry_is_unknown_not_zero(self):
        response = {
            "prompt_eval_count": 1001,
            "prompt_eval_duration": 1_000_000_000,
            "eval_count": 1,
            "eval_duration": 10_000_000,
        }
        with patch.object(ollama_diagnostics, "post_json", return_value=response):
            observations = ollama_diagnostics.benchmark_prefill(
                "http://127.0.0.1:11434", "qwen3:8b", [2]
            )
        self.assertIsNone(observations[0]["prompt_eval_cached_count"])
        self.assertIsNone(observations[0]["prompt_eval_uncached_count"])
        self.assertIsNone(observations[0]["uncached_prefill_tokens_per_second"])


if __name__ == "__main__":
    unittest.main()
