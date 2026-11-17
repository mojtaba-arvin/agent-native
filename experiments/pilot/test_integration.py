"""End-to-end mock conformance test; this is NOT an AI-agent trial.

The scripted driver exercises the public gateway, candidate format, trusted
finalizer, and E-007 metrics in both arms. It must never be reported as model
productivity, quality, or cost evidence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from finalize import finalize_run
from gateway import PilotGateway


TASK_ID = "pilot-catalog-add-readonly-operation"
MODEL_ID = "mock-adapter-conformance-only"


class MockPipelineConformanceTests(unittest.TestCase):
    def _run_mock_arm(self, arm: str, root: Path) -> dict:
        run_id = f"mock-conformance-{arm}"
        events = []
        gateway = PilotGateway(
            arm,
            max_tool_calls=40,
            trace_sink=events.append,
            trace_context={
                "run_id": run_id,
                "candidate_id": arm,
                "model_id": MODEL_ID,
                "task_id": TASK_ID,
                "attempt": 1,
            },
        )
        usage_ack = gateway.handle_message({
            "type": "model_usage",
            "request_id": f"{arm}-mock-generation-1",
            "input_tokens": 1000,
            "output_tokens": 250,
            "cost_usd": 0.0005,
        })
        self.assertTrue(usage_ack["accepted"])
        session = gateway.session_message()
        self.assertNotIn("disclosure_arm", session["surface"])
        self.assertNotIn(arm, json.dumps(session["surface"], sort_keys=True))

        request_number = 0

        def record_usage(request_id: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
            acknowledgement = gateway.handle_message({
                "type": "model_usage",
                "request_id": request_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            })
            self.assertTrue(acknowledgement["accepted"])

        def call(tool: str, arguments: dict) -> dict:
            nonlocal request_number
            request_number += 1
            # Synthetic provider telemetry for adapter/gateway conformance only.
            record_usage(
                f"{arm}-{request_number}-usage",
                1000 + request_number,
                40 + request_number,
                0.001,
            )
            response = gateway.handle_message({
                "type": "tool_call",
                "request_id": f"{arm}-{request_number}",
                "tool": tool,
                "arguments": arguments,
            })
            self.assertIn("response", response)
            return response["response"]

        def discover(tool: str) -> None:
            if arm == "progressive":
                response = call("interface.describe", {"name": tool})
                self.assertTrue(response["ok"], response["diagnostics"])
                self.assertEqual(response["result"]["name"], tool)
                self.assertIn("input_schema", response["result"])

        discover("service.inspect")
        inspected = call("service.inspect", {"service_id": "catalog"})
        self.assertTrue(inspected["ok"], inspected["diagnostics"])
        base_revision = inspected["result"]["revision"]

        discover("service.propose")
        proposed_ir = copy.deepcopy(gateway.interface.services["catalog"])
        proposed_ir["operations"].append({
            "name": "get_item_by_name",
            "method": "GET",
            "path": "/items/by-name/{name}",
            "input": [{"name": "name", "type": "String", "source": "path"}],
            "output": "Item",
            "errors": ["InvalidInput", "NotFound", "Unauthorized"],
            "validation": ["name.non_empty"],
            "effects": ["repository.read"],
            "capability": "items.read",
        })
        proposed = call("service.propose", {
            "service_id": "catalog",
            "base_revision": base_revision,
            "ir": proposed_ir,
        })
        self.assertTrue(proposed["ok"], proposed["diagnostics"])
        change_set_id = proposed["result"]["change_set_id"]

        discover("service.validate")
        validated = call("service.validate", {"change_set_id": change_set_id})
        self.assertTrue(validated["ok"], validated["diagnostics"])
        self.assertTrue(validated["result"]["valid"])

        discover("service.plan")
        planned = call("service.plan", {"change_set_id": change_set_id})
        self.assertTrue(planned["ok"], planned["diagnostics"])
        self.assertTrue(planned["result"]["valid"])
        self.assertFalse(planned["result"]["will_mutate"])
        self.assertFalse(planned["result"]["will_deploy"])

        # Model's final JSON response also contributes usage, even though it
        # does not invoke a tool.
        record_usage(f"{arm}-final-usage", 900, 30, 0.0005)

        candidate = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "service_id": "catalog",
            "base_revision": base_revision,
            "change_set_id": change_set_id,
            "ir": proposed_ir,
        }
        candidate_bytes = (
            json.dumps(candidate, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")

        trace_path = root / f"{arm}.trace.jsonl"
        candidate_path = root / f"{arm}.candidate.json"
        evaluation_path = root / f"{arm}.evaluation.json"
        finalized_path = root / f"{arm}.finalized.jsonl"
        summary_path = root / f"{arm}.summary.json"

        trace_path.write_text(
            "".join(
                json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
                for event in events
            ),
            encoding="utf-8",
        )
        candidate_path.write_bytes(candidate_bytes)

        agent_finished_at_ns = max(event["timestamp_ns"] for event in events) + 1_000_000
        evaluation_result = {
            "schema_version": 1,
            "run_id": run_id,
            "candidate_id": arm,
            "task_id": TASK_ID,
            "attempt": 1,
            "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "accepted": True,
            "eligible_for_acceptance": True,
            "failure_class": None,
            "agent_finished_at_ns": agent_finished_at_ns,
            "evaluated_at_ns": agent_finished_at_ns + 1_000_000,
            "evaluator_version": "mock-conformance-only",
        }
        evaluation_path.write_text(
            json.dumps(evaluation_result, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

        return finalize_run(
            trace_path=trace_path,
            evaluation_result_path=evaluation_path,
            candidate_path=candidate_path,
            output_trace_path=finalized_path,
            output_summary_path=summary_path,
        )

    def test_full_mock_pipeline_is_wired_for_both_disclosure_arms(self):
        # The local fake evaluator result below verifies only integration.
        # It is not produced by ORACLE_CONTRACT.md and is not benchmark data.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            progressive = self._run_mock_arm("progressive", root)
            upfront = self._run_mock_arm("upfront", root)

        for result in (progressive, upfront):
            self.assertEqual(result["task_count"], 1)
            self.assertEqual(result["eligible_task_count"], 1)
            self.assertEqual(result["accepted_tasks"], 1)
            self.assertEqual(result["acceptance_rate"], 1.0)
            self.assertTrue(result["tasks"][0]["token_usage_complete"])
            self.assertTrue(result["tasks"][0]["cost_complete"])
            self.assertEqual(result["tasks"][0]["tool_errors"], 0)

        progressive_task = progressive["tasks"][0]
        upfront_task = upfront["tasks"][0]
        self.assertEqual(progressive_task["schema_lookup_calls"], 4)
        self.assertEqual(upfront_task["schema_lookup_calls"], 0)
        self.assertEqual(progressive_task["tool_calls"], upfront_task["tool_calls"] + 4)
        self.assertGreater(progressive_task["total_tokens"], upfront_task["total_tokens"])
        self.assertGreater(progressive_task["inference_cost_usd"], upfront_task["inference_cost_usd"])


if __name__ == "__main__":
    unittest.main()
