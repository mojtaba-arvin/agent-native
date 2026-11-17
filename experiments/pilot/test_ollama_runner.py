from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from schedule import SOURCE_FILES

from ollama_runner import (
    TrialFailure,
    _map_provider_tool_call,
    build_ollama_options,
    run_one_trial,
    validate_local_ollama_url,
)


class FakeOllamaHandler(BaseHTTPRequestHandler):
    requests_seen = []
    response_index = 0
    lock = threading.Lock()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        with type(self).lock:
            type(self).requests_seen.append(payload)
            index = type(self).response_index
            type(self).response_index += 1

        if index == 0:
            response = {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "agent.invoke",
                            "arguments": {
                                "request_id": "model-call-001",
                                "tool": "interface.describe",
                                "arguments": {"name": "service.inspect"},
                            },
                        },
                    }],
                },
                "prompt_eval_count": 120,
                "eval_count": 34,
                "done": True,
            }
        else:
            response = {
                "message": {"role": "assistant", "content": "{}"},
                "prompt_eval_count": 170,
                "eval_count": 5,
                "done": True,
            }

        raw = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format, *args):
        return


class OllamaRunnerTests(unittest.TestCase):
    def setUp(self):
        FakeOllamaHandler.requests_seen = []
        FakeOllamaHandler.response_index = 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_schedule_schema_pins_exact_runtime_source_set(self):
        schema_path = Path(__file__).with_name("schedule.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        source_schema = schema["$defs"]["source_hashes"]
        self.assertEqual(set(source_schema["required"]), set(SOURCE_FILES))
        self.assertEqual(set(source_schema["properties"]), set(SOURCE_FILES))

    def test_loopback_endpoint_is_required(self):
        self.assertTrue(validate_local_ollama_url("http://localhost:11434").endswith("/api/chat"))
        with self.assertRaisesRegex(ValueError, "loopback"):
            validate_local_ollama_url("https://ollama.com")
        with self.assertRaisesRegex(ValueError, "loopback"):
            validate_local_ollama_url("http://192.0.2.10:11434")

    def test_generation_settings_are_pinned_and_output_is_capped(self):
        options, think = build_ollama_options(
            {
                "temperature": 0.2,
                "top_p": 0.9,
                "seed": 17,
                "num_ctx": 8192,
                "think": True,
            },
            4000,
        )
        self.assertEqual(options["num_predict"], 4000)
        self.assertEqual(options["seed"], 17)
        self.assertIs(think, True)
        with self.assertRaisesRegex(ValueError, "must_pin"):
            build_ollama_options({"temperature": 0.2}, 4000)
        with self.assertRaisesRegex(ValueError, "exceeds_output_budget"):
            build_ollama_options(
                {
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "seed": 17,
                    "num_ctx": 8192,
                    "think": True,
                    "num_predict": 5000,
                },
                4000,
            )

    def test_invalid_provider_tool_call_is_not_silently_repaired(self):
        mapped = _map_provider_tool_call(
            {"function": {"name": "other.tool", "arguments": {"anything": 1}}},
            3,
        )
        self.assertEqual(mapped["tool"], "<invalid>")
        self.assertEqual(mapped["request_id"], "invalid-call-3")

    def test_scheduled_trial_runs_through_gateway_and_preserves_trace(self):
        trial = {
            "sequence": 1,
            "pair_id": "pair-0001",
            "run_id": "pair-0001-progressive-test",
            "candidate_id": "progressive",
            "model_id": "qwen3-test",
            "generation_settings": {
                "temperature": 0.2,
                "top_p": 0.9,
                "seed": 17,
                "num_ctx": 8192,
                "think": True,
            },
            "task_id": "pilot-catalog-add-readonly-operation",
            "attempt": 1,
            "source_revision": "a" * 40,
            "fresh_state_required": True,
            "agent_visible_treatment_label": False,
            "budgets": {
                "max_input_tokens": 16000,
                "max_output_tokens": 4000,
                "max_tool_calls": 10,
                "max_wall_seconds": 30,
            },
        }

        with tempfile.TemporaryDirectory() as temporary:
            record = run_one_trial(
                trial,
                plan_id="b" * 64,
                results_root=Path(temporary) / "results",
                base_url=self.base_url,
            )
            run_dir = Path(temporary) / "results" / trial["run_id"]
            trace = [
                json.loads(line)
                for line in (run_dir / "gateway.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["failure_class"], "INVALID_CANDIDATE")
        self.assertEqual(record["evaluator_status"], "not_run")
        self.assertTrue(record["agent_finished_at_ns"] > record["agent_started_at_ns"])
        self.assertEqual(
            [event["event_type"] for event in trace],
            ["task_started", "runtime_metric", "model_usage", "tool_call", "model_usage"],
        )
        self.assertEqual(trace[2]["input_tokens"], 120)
        self.assertEqual(trace[2]["output_tokens"], 34)
        self.assertEqual(trace[3]["tool_name"], "interface.describe")
        self.assertTrue(trace[3]["schema_lookup"])
        self.assertEqual(trace[4]["input_tokens"], 170)
        self.assertEqual(trace[4]["output_tokens"], 5)

        requests = FakeOllamaHandler.requests_seen
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["model"], "qwen3-test")
        self.assertEqual(len(requests[0]["tools"]), 1)
        self.assertEqual(requests[0]["tools"][0]["function"]["name"], "agent.invoke")
        self.assertEqual(requests[0]["options"]["num_predict"], 4000)
        self.assertNotIn("candidate_id", json.dumps(requests[0]["messages"]))
        self.assertNotIn('"progressive"', json.dumps(requests[0]["messages"]))
        self.assertTrue(any(message["role"] == "tool" for message in requests[1]["messages"]))


if __name__ == "__main__":
    unittest.main()
