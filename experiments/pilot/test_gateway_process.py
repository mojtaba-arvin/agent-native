"""Subprocess-level tests for the real NDJSON gateway CLI.

These tests exercise transport and process behavior only. They do not call an
AI provider and are not evidence about model-agent performance.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATEWAY = Path(__file__).with_name("gateway.py")
TASK_ID = "pilot-catalog-add-readonly-operation"


class GatewayProcessTests(unittest.TestCase):
    def test_cli_session_usage_tool_dispatch_and_budget_enforcement(self):
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "process.trace.jsonl"
            command = [
                sys.executable,
                str(GATEWAY),
                "--arm", "progressive",
                "--run-id", "subprocess-run-001",
                "--candidate-id", "progressive",
                "--model-id", "process-conformance-only",
                "--task-id", TASK_ID,
                "--attempt", "1",
                "--max-tool-calls", "1",
                "--trace-output", str(trace_path),
            ]
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            try:
                self.assertIsNotNone(process.stdin)
                self.assertIsNotNone(process.stdout)

                session_line = process.stdout.readline()
                self.assertTrue(session_line, "gateway exited before sending its session")
                session = json.loads(session_line)
                self.assertEqual(session["type"], "session")
                self.assertEqual(session["protocol_version"], "0.1")
                self.assertNotIn("disclosure_arm", session["surface"])
                self.assertEqual(
                    sum("input_schema" in tool for tool in session["surface"]["tools"]),
                    1,
                )

                usage = {
                    "type": "model_usage",
                    "request_id": "provider-response-001",
                    "input_tokens": 450,
                    "output_tokens": 73,
                    "cost_usd": 0.0012,
                }
                process.stdin.write(json.dumps(usage) + "\n")
                process.stdin.flush()
                usage_ack = json.loads(process.stdout.readline())
                self.assertEqual(usage_ack["type"], "telemetry_ack")
                self.assertTrue(usage_ack["accepted"])

                first_call = {
                    "type": "tool_call",
                    "request_id": "tool-call-001",
                    "tool": "interface.describe",
                    "arguments": {},
                }
                process.stdin.write(json.dumps(first_call) + "\n")
                process.stdin.flush()
                first_result = json.loads(process.stdout.readline())
                self.assertEqual(first_result["type"], "tool_result")
                self.assertTrue(first_result["response"]["ok"])

                over_budget_call = {
                    "type": "tool_call",
                    "request_id": "tool-call-002",
                    "tool": "service.inspect",
                    "arguments": {"service_id": "catalog"},
                }
                process.stdin.write(json.dumps(over_budget_call) + "\n")
                process.stdin.flush()
                over_budget_result = json.loads(process.stdout.readline())
                self.assertEqual(over_budget_result["type"], "tool_result")
                self.assertFalse(over_budget_result["response"]["ok"])
                self.assertEqual(
                    over_budget_result["response"]["diagnostics"][0]["code"],
                    "TOOL_CALL_BUDGET_EXCEEDED",
                )

                process.stdin.close()
                return_code = process.wait(timeout=10)
                remaining_stdout = process.stdout.read()
                stderr = process.stderr.read()
                self.assertEqual(return_code, 0, stderr)
                self.assertEqual(remaining_stdout, "")
                self.assertTrue(trace_path.exists())
                self.assertEqual(
                    stat.S_IMODE(trace_path.stat().st_mode),
                    0o600,
                )

                events = [
                    json.loads(line)
                    for line in trace_path.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(
                    [event["event_type"] for event in events],
                    [
                        "task_started",
                        "runtime_metric",
                        "model_usage",
                        "tool_call",
                        "tool_call",
                    ],
                )
                self.assertEqual(events[2]["input_tokens"], 450)
                self.assertEqual(events[2]["output_tokens"], 73)
                self.assertEqual(events[2]["cost_usd"], 0.0012)
                self.assertEqual(events[3]["tool_name"], "interface.describe")
                self.assertNotIn("failure_class", events[3])
                self.assertEqual(events[4]["tool_name"], "service.inspect")
                self.assertEqual(events[4]["failure_class"], "TOOL_CALL_BUDGET_EXCEEDED")
                self.assertTrue(all(event["run_id"] == "subprocess-run-001" for event in events))
                self.assertTrue(all(event["candidate_id"] == "progressive" for event in events))
                self.assertTrue(all(event["model_id"] == "process-conformance-only" for event in events))
                self.assertEqual(
                    [event["timestamp_ns"] for event in events],
                    sorted(event["timestamp_ns"] for event in events),
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()


if __name__ == "__main__":
    unittest.main()
