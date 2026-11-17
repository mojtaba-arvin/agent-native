from __future__ import annotations

import unittest
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

        def fake_post(url, payload, timeout=300.0):
            requests.append(payload)
            return responses.pop(0)

        with patch.object(ollama_diagnostics, "post_json", side_effect=fake_post):
            observations = ollama_diagnostics.benchmark_prefill(
                "http://127.0.0.1:11434", "qwen3:8b", [2]
            )

        self.assertEqual(len(observations), 8)
        self.assertEqual(len(requests), 8)
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
