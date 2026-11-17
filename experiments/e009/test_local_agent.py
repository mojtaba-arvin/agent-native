from __future__ import annotations

import copy
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

from kernel import load_service_ir
from local_agent import (
    AgentRunError,
    EXPECTED_OPERATION,
    SERVICE_ID,
    TASK_ID,
    digest,
    run,
    validate_ollama_endpoint,
    verify_candidate,
    _plan_gate_response,
    _persist_candidate_response,
    _proposal_budget_response,
    _proposal_attempt_gate,
    _compact_conversation,
)


class LocalAgentRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parent / "catalog.an").read_text(encoding="utf-8")
        cls.ir = load_service_ir(cls.source)
        cls.inspected = {
            "service": cls.ir["service"],
            "types": cls.ir["types"],
            "operations": [
                {"name": item["name"], "method": item["method"], "path": item["path"]}
                for item in cls.ir["operations"]
            ],
            "revision": digest(cls.ir),
        }
        cls.inspected_operations = {
            item["name"]: copy.deepcopy(item) for item in cls.ir["operations"]
        }

    def fixture(self):
        ir = copy.deepcopy(self.ir)
        ir["operations"].append(copy.deepcopy(EXPECTED_OPERATION))
        proposal = {
            "service_id": SERVICE_ID,
            "base_revision": self.inspected["revision"],
            "ir": ir,
        }
        change_set_id = digest(proposal)
        candidate = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "service_id": SERVICE_ID,
            "base_revision": self.inspected["revision"],
            "change_set_id": change_set_id,
            "ir": ir,
        }
        successful_proposal = {
            "arguments": {
                "service_id": SERVICE_ID,
                "base_revision": self.inspected["revision"],
                "ir": ir,
            },
            "result": {"change_set_id": change_set_id},
        }
        validation = {"ok": True, "result": {"valid": True}}
        plan = {
            "ok": True,
            "result": {
                "valid": True,
                "will_mutate": False,
                "will_deploy": False,
                "effects": ["repository.read", "repository.write", "queue.submit", "queue.read", "queue.cancel"],
            },
        }
        sequence = [
            "interface.describe",
            "service.inspect",
            *["service.inspect" for _ in self.inspected_operations],
            "service.propose",
            "service.validate",
            "service.plan",
        ]
        return candidate, successful_proposal, validation, plan, sequence

    def verify(self, candidate, proposal, validation, plan, sequence, inspected_operations=None, validation_id=None, plan_id=None):
        return verify_candidate(
            candidate,
            inspected=self.inspected,
            inspected_operations=(
                self.inspected_operations if inspected_operations is None else inspected_operations
            ),
            successful_proposal=proposal,
            validation_result=validation,
            plan_result=plan,
            tool_sequence=sequence,
            validation_change_set_id=(proposal["result"]["change_set_id"] if validation_id is None else validation_id),
            plan_change_set_id=(proposal["result"]["change_set_id"] if plan_id is None else plan_id),
        )

    def test_accepts_exact_readonly_proposal_with_full_inspection(self):
        values = self.fixture()
        result = self.verify(*values)
        self.assertEqual(result["added_operation"], "get_item_by_normalized_name")
        self.assertEqual(result["validation"], "passed")
        self.assertEqual(result["plan"], "valid_no_mutation_no_deployment")

    def test_accepts_one_bounded_repair_before_final_validation_and_plan(self):
        values = list(self.fixture())
        values[4] = [
            *values[4][: -3],
            "service.propose",
            "service.validate",
            "service.propose",
            "service.validate",
            "service.plan",
        ]
        result = self.verify(*values)
        self.assertEqual(result["validation"], "passed")

    def test_rejects_validation_or_plan_for_a_different_proposal_hash(self):
        values = self.fixture()
        with self.assertRaisesRegex(AgentRunError, "candidate_validation_hash_mismatch"):
            self.verify(*values, validation_id="0" * 64)
        with self.assertRaisesRegex(AgentRunError, "candidate_plan_hash_mismatch"):
            self.verify(*values, plan_id="0" * 64)

    def test_rejects_more_than_three_proposal_attempts(self):
        values = list(self.fixture())
        values[4] = [
            *values[4][: -3],
            "service.propose", "service.validate",
            "service.propose", "service.validate",
            "service.propose", "service.validate",
            "service.propose", "service.validate",
            "service.plan",
        ]
        with self.assertRaisesRegex(AgentRunError, "required_tool_sequence_invalid"):
            self.verify(*values)

    def test_rejects_changed_existing_operation(self):
        values = list(self.fixture())
        values[0]["ir"]["operations"][0]["capability"] = "admin"
        proposal = {
            "service_id": SERVICE_ID,
            "base_revision": values[0]["base_revision"],
            "ir": values[0]["ir"],
        }
        change_set_id = digest(proposal)
        values[0]["change_set_id"] = change_set_id
        values[1]["arguments"]["ir"] = values[0]["ir"]
        values[1]["result"]["change_set_id"] = change_set_id
        with self.assertRaisesRegex(AgentRunError, "candidate_modified_existing_operations"):
            self.verify(*values)

    def test_rejects_incomplete_inspection(self):
        values = self.fixture()
        with self.assertRaisesRegex(AgentRunError, "not_all_existing_operations_were_inspected"):
            self.verify(*values, inspected_operations={})

    def test_rejects_missing_validation_or_mutating_plan(self):
        values = list(self.fixture())
        values[2] = {"ok": True, "result": {"valid": False}}
        with self.assertRaisesRegex(AgentRunError, "proposal_validation_not_successful"):
            self.verify(*values)

        values = list(self.fixture())
        values[3]["result"]["will_mutate"] = True
        with self.assertRaisesRegex(AgentRunError, "proposal_plan_not_safe"):
            self.verify(*values)

    def test_rejects_apply_or_wrong_tool_order(self):
        values = list(self.fixture())
        values[4].append("service.apply")
        with self.assertRaisesRegex(AgentRunError, "required_tool_sequence_invalid"):
            self.verify(*values)

        values = list(self.fixture())
        values[4] = [item for item in values[4] if item != "service.inspect"]
        with self.assertRaisesRegex(AgentRunError, "required_tool_sequence_invalid"):
            self.verify(*values)

    def test_rejects_wrong_added_operation_or_effect(self):
        values = list(self.fixture())
        values[0]["ir"]["operations"][-1]["effects"] = ["network.egress"]
        proposal = {
            "service_id": SERVICE_ID,
            "base_revision": values[0]["base_revision"],
            "ir": values[0]["ir"],
        }
        change_set_id = digest(proposal)
        values[0]["change_set_id"] = change_set_id
        values[1]["arguments"]["ir"] = values[0]["ir"]
        values[1]["result"]["change_set_id"] = change_set_id
        with self.assertRaisesRegex(AgentRunError, "candidate_new_operation_does_not_match_task"):
            self.verify(*values)

    def test_full_runner_gateway_provider_protocol_with_deterministic_provider(self):
        candidate_ir = copy.deepcopy(self.ir)
        candidate_ir["operations"].append(copy.deepcopy(EXPECTED_OPERATION))
        proposal = {
            "service_id": SERVICE_ID,
            "base_revision": self.inspected["revision"],
            "ir": candidate_ir,
        }
        change_set_id = digest(proposal)
        calls = [
            ("interface.describe", {"name": "service.inspect"}),
            ("service.inspect", {"service_id": SERVICE_ID}),
        ]
        calls.extend(
            ("service.inspect", {"service_id": SERVICE_ID, "operation": name})
            for name in self.inspected_operations
        )
        calls.extend([
            ("service.propose", proposal),
            ("service.validate", {"change_set_id": change_set_id}),
            ("service.plan", {"change_set_id": change_set_id}),
        ])
        responses = []
        for index, (tool, arguments) in enumerate(calls, 1):
            responses.append({
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "agent.invoke",
                            "arguments": {
                                "request_id": f"mock-request-{index}",
                                "tool": tool,
                                "arguments": arguments,
                            },
                        },
                    }],
                },
                "prompt_eval_count": 40,
                "eval_count": 4,
            })
        candidate = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "service_id": SERVICE_ID,
            "base_revision": self.inspected["revision"],
            "change_set_id": change_set_id,
            "ir": candidate_ir,
        }
        responses.append({
            "message": {
                "role": "assistant",
                "content": json.dumps(candidate, ensure_ascii=False, sort_keys=True),
                "tool_calls": [],
            },
            "prompt_eval_count": 45,
            "eval_count": 80,
        })

        class Handler(BaseHTTPRequestHandler):
            index = 0
            response_values = responses

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                if type(self).index >= len(type(self).response_values):
                    self.send_error(500)
                    return
                value = type(self).response_values[type(self).index]
                type(self).index += 1
                raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="agent-native-e009-", dir="/tmp") as temp:
                args = SimpleNamespace(
                    model="deterministic-test-double",
                    ollama_url=f"http://127.0.0.1:{server.server_port}",
                    arm="progressive",
                    results_dir=Path(temp) / "results",
                    max_input_tokens=2000,
                    max_output_tokens=1000,
                    max_tool_calls=20,
                    max_wall_seconds=30.0,
                    num_ctx=4096,
                    num_predict=256,
                    temperature=0.0,
                    top_p=1.0,
                    seed=7,
                    think=False,
                )
                result = run(args)
                self.assertEqual(result["status"], "candidate_verified_locally")
                self.assertEqual(result["tool_calls"], len(calls))
                self.assertEqual(result["input_tokens"], 40 * len(calls) + 45)
                self.assertEqual(result["output_tokens"], 4 * len(calls) + 80)
                self.assertEqual(
                    result["verification"]["added_operation"],
                    "get_item_by_normalized_name",
                )
                run_dir = Path(result["candidate_path"]).parent
                self.assertTrue((run_dir / "tool-trace.jsonl").is_file())
                self.assertEqual(stat.S_IMODE((run_dir / "candidate.json").stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
                self.assertEqual(Handler.index, len(responses))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_runner_stops_after_repeating_an_identical_invalid_tool_call(self):
        invalid_call = {
            "function": {
                "name": "agent.invoke",
                "arguments": {
                    "request_id": "same-invalid-request",
                    "tool": "service.inspect",
                    "arguments": {},
                },
            },
        }
        responses = [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [copy.deepcopy(invalid_call)],
                },
                "prompt_eval_count": 30,
                "eval_count": 12,
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [copy.deepcopy(invalid_call)],
                },
                "prompt_eval_count": 35,
                "eval_count": 12,
            },
        ]

        class Handler(BaseHTTPRequestHandler):
            index = 0
            response_values = responses

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                if type(self).index >= len(type(self).response_values):
                    self.send_error(500)
                    return
                value = type(self).response_values[type(self).index]
                type(self).index += 1
                raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="agent-native-e009-", dir="/tmp") as temp:
                args = SimpleNamespace(
                    model="deterministic-test-double",
                    ollama_url=f"http://127.0.0.1:{server.server_port}",
                    arm="upfront",
                    results_dir=Path(temp) / "results",
                    max_input_tokens=2000,
                    max_output_tokens=1000,
                    max_tool_calls=20,
                    max_wall_seconds=30.0,
                    num_ctx=4096,
                    num_predict=256,
                    temperature=0.0,
                    top_p=1.0,
                    seed=7,
                    think=False,
                )
                result = run(args)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["failure"], "AgentRunError:repeated_invalid_tool_call")
                self.assertEqual(result["tool_calls"], 2)
                run_dirs = list((Path(temp) / "results").iterdir())
                self.assertEqual(len(run_dirs), 1)
                trace = run_dirs[0] / "tool-trace.jsonl"
                events = [
                    json.loads(line)
                    for line in trace.read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(len(events), 2)
                self.assertEqual(
                    [event["response"]["diagnostics"][0]["code"] for event in events],
                    ["ARGUMENTS_REQUIRED", "ARGUMENTS_REQUIRED"],
                )
                self.assertEqual(Handler.index, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_compacted_conversation_preserves_exact_gateway_state_and_latest_diagnostics(self):
        base = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "user", "content": "tool schemas"},
        ]
        operation = copy.deepcopy(self.inspected_operations["get_item_by_name"])
        diagnostics = [{
            "code": "IR_PRESERVATION_MISMATCH",
            "message": "changed existing operation",
            "fix_hint": "Copy the exact inspected declaration",
        }]
        compacted = _compact_conversation(
            base,
            self.inspected,
            {"get_item_by_name": operation},
            ["service.inspect", "service.propose"],
            [
                {"tool": "service.inspect", "ok": True},
                {
                    "tool": "service.propose",
                    "ok": False,
                    "diagnostics": diagnostics,
                    "next_actions": ["Correct the complete IR"],
                },
            ],
        )
        self.assertEqual(compacted[:3], base)
        self.assertEqual(len(compacted), 4)
        self.assertEqual([item["role"] for item in compacted], ["system", "user", "user", "user"])
        ledger = json.loads(compacted[3]["content"].split("\\n", 1)[1])
        self.assertEqual(ledger["service_inspection"], self.inspected)
        self.assertEqual(
            ledger["operation_inspections"]["get_item_by_name"],
            operation,
        )
        self.assertEqual(ledger["tool_sequence"], ["service.inspect", "service.propose"])
        self.assertEqual(ledger["recent_tool_outcomes"][-1]["diagnostics"], diagnostics)
        self.assertEqual(ledger["recent_tool_outcomes"][-1]["next_actions"], ["Correct the complete IR"])
        self.assertNotIn("assistant", [item["role"] for item in compacted])
        self.assertNotIn("tool_calls", compacted[3]["content"])

    def test_ollama_endpoint_is_strictly_loopback_ip(self):
        self.assertEqual(validate_ollama_endpoint("http://127.0.0.1:11434"), ("127.0.0.1", 11434))
        with self.assertRaises(ValueError):
            validate_ollama_endpoint("http://example.com:11434")
        with self.assertRaises(ValueError):
            validate_ollama_endpoint("https://127.0.0.1:11434")
        with self.assertRaises(ValueError):
            validate_ollama_endpoint("http://127.0.0.1:11434/api/chat")



    def test_invalid_validation_blocks_plan_even_when_outer_tool_ok_is_true(self):
        proposal_id = "a" * 64
        request = {"request_id": "premature-plan", "arguments": {"change_set_id": proposal_id}}
        response = _plan_gate_response(
            request,
            {"result": {"change_set_id": proposal_id}},
            {"ok": True, "result": {"valid": False, "diagnostics": [{"code": "AN021"}]}},
            proposal_id,
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "VALIDATION_REQUIRED")
        self.assertIn("complete IR snapshot", response["diagnostics"][0]["fix_hint"])

    def test_plan_guard_requires_validation_for_the_same_proposal_hash(self):
        first_id, second_id = "a" * 64, "b" * 64
        request = {"request_id": "mismatched-plan", "arguments": {"change_set_id": second_id}}
        response = _plan_gate_response(
            request,
            {"result": {"change_set_id": first_id}},
            {"ok": True, "result": {"valid": True}},
            first_id,
        )
        self.assertEqual(response["diagnostics"][0]["code"], "VALIDATION_REQUIRED")

    def test_plan_guard_allows_only_the_validated_current_proposal(self):
        proposal_id = "c" * 64
        request = {"request_id": "valid-plan", "arguments": {"change_set_id": proposal_id}}
        response = _plan_gate_response(
            request,
            {"result": {"change_set_id": proposal_id}},
            {"ok": True, "result": {"valid": True}},
            proposal_id,
        )
        self.assertIsNone(response)


    def test_final_json_candidate_is_preserved_before_semantic_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate_path = root / "candidate.json"
            record = {"candidate_path": None}
            raw = b'{"ir_version":1,"service":{"name":"Catalog","version":"1"}}'
            _persist_candidate_response(candidate_path, raw, record)
            self.assertEqual(record["candidate_path"], str(candidate_path))
            self.assertEqual(json.loads(candidate_path.read_text(encoding="utf-8")), {
                "ir_version": 1,
                "service": {"name": "Catalog", "version": "1"},
            })
            self.assertEqual(stat.S_IMODE(candidate_path.stat().st_mode), 0o600)


    def test_proposal_attempt_gate_counts_rejected_attempts_and_blocks_attempt_four(self):
        request = {"request_id": "budget"}
        attempts = 0
        for expected in (1, 2, 3):
            attempts, response = _proposal_attempt_gate(request, attempts)
            self.assertEqual(attempts, expected)
            self.assertIsNone(response)
        attempts, response = _proposal_attempt_gate(request, attempts)
        self.assertEqual(attempts, 4)
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "PROPOSAL_REPAIR_BUDGET_EXCEEDED")

    def test_proposal_repair_budget_response_is_explicit_and_fail_closed(self):
        response = _proposal_budget_response({"request_id": "fourth-proposal"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "PROPOSAL_REPAIR_BUDGET_EXCEEDED")

if __name__ == "__main__":
    unittest.main()
