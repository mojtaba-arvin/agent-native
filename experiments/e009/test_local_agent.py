from __future__ import annotations

import copy
import json
import os
import stat
import sys
import tempfile
import time
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

import local_agent
from kernel import load_service_ir
from local_agent import (
    AgentRunError,
    provider_chat,
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
    _is_proposal_budget_exhausted,
    prevalidate_catalog_operation,
    prevalidate_tool_call,
    prevalidation_repair_key,
    _resolve_task_path,
    _compact_conversation,
    _build_compaction_ledger,
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

    def verify(self, candidate, proposal, validation, plan, sequence, inspected_operations=None, validation_id=None, plan_id=None, proposal_mode="snapshot", base_disclosure="per_operation"):
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
            proposal_mode=proposal_mode,
            base_disclosure=base_disclosure,
        )

    def test_task_path_none_resolves_to_default_agent_task(self):
        expected = (Path(__file__).parent / "AGENT_TASK.md").resolve()
        self.assertEqual(_resolve_task_path(None), expected)

    def test_delta_mode_resolves_to_delta_specific_task_contract(self):
        expected = (Path(__file__).parent / "AGENT_TASK_DELTA.md").resolve()
        self.assertEqual(_resolve_task_path(None, "delta"), expected)

    def test_explicit_task_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            explicit = Path(temporary) / "custom-task.md"
            explicit.write_text("test task", encoding="utf-8")
            self.assertEqual(_resolve_task_path(explicit), explicit.resolve())

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
                prompt_states = [
                    json.loads(line)
                    for line in (run_dir / "prompt-states.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(len(prompt_states), Handler.index)
                self.assertEqual(prompt_states[0]["kind"], "initial_session_surface")
                self.assertEqual(prompt_states[1]["kind"], "gateway_state_ledger")
                self.assertTrue(all(item["state_sha256"] == digest(item["state"]) for item in prompt_states))
                provider_rows = [
                    json.loads(line)
                    for line in (run_dir / "provider-responses.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(
                    [item["prompt_state_sha256"] for item in provider_rows],
                    [item["state_sha256"] for item in prompt_states],
                )
                self.assertTrue(all(len(item["payload_sha256"]) == 64 for item in provider_rows))
                self.assertEqual([item["payload_metadata"]["turn"] for item in provider_rows],
                                 list(range(1, len(provider_rows) + 1)))
                self.assertTrue(all(item["payload_metadata"]["keep_alive"] == "10m" for item in provider_rows))
                self.assertEqual(stat.S_IMODE((run_dir / "candidate.json").stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(run_dir.stat().st_mode), 0o700)
                self.assertEqual(Handler.index, len(responses))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_propose_prevalidation_allows_distinct_repairs_but_stops_on_repeat(self):
        surface = {
            "tools": [{
                "name": "service.propose",
                "input_schema": {
                    "type": "object",
                    "required": ["service_id", "base_revision", "ir"],
                },
            }],
        }
        missing_service = prevalidate_tool_call(
            {
                "request_id": "propose-missing-service",
                "tool": "service.propose",
                "arguments": {"base_revision": "revision", "ir": {}},
            },
            surface,
        )
        missing_snapshot = prevalidate_tool_call(
            {
                "request_id": "propose-missing-snapshot",
                "tool": "service.propose",
                "arguments": {"service_id": "catalog", "operation": "get_item_by_normalized_name"},
            },
            surface,
        )
        self.assertIsNotNone(missing_service)
        self.assertIsNotNone(missing_snapshot)
        self.assertIn("service_id", missing_service["diagnostics"][0]["message"])
        self.assertIn("complete canonical service snapshot", missing_snapshot["diagnostics"][0]["fix_hint"])

        first_key = prevalidation_repair_key("service.propose", missing_service["diagnostics"][0])
        second_key = prevalidation_repair_key("service.propose", missing_snapshot["diagnostics"][0])
        self.assertNotEqual(first_key, second_key)
        repaired = {first_key}
        self.assertNotIn(second_key, repaired)
        repaired.add(second_key)
        self.assertIn(
            second_key,
            {prevalidation_repair_key("service.propose", missing_snapshot["diagnostics"][0])},
        )

    def test_runner_stops_after_repeated_service_inspection_without_operation(self):
        def invoke(request_id):
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "agent.invoke",
                            "arguments": {
                                "request_id": request_id,
                                "tool": "service.inspect",
                                "arguments": {"service_id": "catalog"},
                            },
                        },
                    }],
                },
                "prompt_eval_count": 30,
                "eval_count": 12,
            }

        responses = [invoke("inspect-1"), invoke("inspect-2"), invoke("inspect-3")]

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
                    model="deterministic-inspection-loop-double",
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
                self.assertEqual(result["failure"], "AgentRunError:inspection_progression_failed")
                self.assertEqual(result["tool_calls"], 3)
                self.assertEqual(Handler.index, 3)
                run_dir = next((Path(temp) / "results").iterdir())
                events = [
                    json.loads(line)
                    for line in (run_dir / "tool-trace.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                self.assertTrue(events[0]["response"]["ok"])
                self.assertEqual(
                    events[1]["response"]["diagnostics"][0]["code"],
                    "INSPECTION_OPERATION_REQUIRED",
                )
                self.assertEqual(
                    events[2]["response"]["diagnostics"][0]["code"],
                    "INSPECTION_PROGRESS_REPAIR_EXHAUSTED",
                )
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
                with patch.object(local_agent, "gateway_exchange", side_effect=AssertionError("invalid call reached Gateway")) as gateway_call:
                    result = run(args)
                self.assertEqual(gateway_call.call_count, 0)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["failure"], "AgentRunError:prevalidation_repair_failed")
                self.assertEqual(result["tool_calls"], 2)
                run_dirs = list((Path(temp) / "results").iterdir())
                self.assertEqual(len(run_dirs), 1)
                trace = run_dirs[0] / "tool-trace.jsonl"
                events = [
                    json.loads(line)
                    for line in trace.read_text(encoding="utf-8").splitlines()
                ]
                prompt_states = [
                    json.loads(line)
                    for line in (run_dirs[0] / "prompt-states.jsonl").read_text(encoding="utf-8").splitlines()
                ]
                self.assertEqual(len(prompt_states), 2)
                self.assertEqual(prompt_states[1]["state"]["tool_sequence"], ["service.inspect"])
                self.assertEqual(
                    prompt_states[1]["state"]["recent_tool_outcomes"][-1]["diagnostics"][0]["code"],
                    "ARGUMENTS_REQUIRED",
                )
                self.assertEqual(len(events), 2)
                self.assertEqual(
                    [event["response"]["diagnostics"][0]["code"] for event in events],
                    ["ARGUMENTS_REQUIRED", "ARGUMENTS_REQUIRED"],
                )
                self.assertTrue(all(event["execution_origin"] == "runner_prevalidation" for event in events))
                self.assertIn('service_id: "catalog"', events[0]["response"]["diagnostics"][0]["message"])
                self.assertEqual(Handler.index, 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


    def _run_catalog_guard_provider_double(self, operation_names):
        calls = [{
            "request_id": "service-inspect",
            "tool": "service.inspect",
            "arguments": {"service_id": "catalog"},
        }]
        calls.extend({
            "request_id": f"operation-inspect-{index}",
            "tool": "service.inspect",
            "arguments": {"service_id": "catalog", "operation": name},
        } for index, name in enumerate(operation_names, 1))
        responses = [{
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": "agent.invoke", "arguments": call}
                }],
            },
            "prompt_eval_count": 30 + index,
            "eval_count": 12,
        } for index, call in enumerate(calls)]
        responses.append({
            "message": {"role": "assistant", "content": "{}", "tool_calls": []},
            "prompt_eval_count": 40,
            "eval_count": 2,
        })

        class Handler(BaseHTTPRequestHandler):
            index = 0
            response_values = responses

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
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
        gateway_calls = []

        def fake_gateway(_process, request):
            gateway_calls.append(copy.deepcopy(request))
            arguments = request["arguments"]
            if "operation" not in arguments:
                result = copy.deepcopy(self.inspected)
            else:
                result = {"operation": copy.deepcopy(self.inspected_operations[arguments["operation"]])}
            return {
                "type": "tool_result",
                "request_id": request["request_id"],
                "response": {"protocol_version": "0.1", "request_id": request["request_id"],
                             "ok": True, "result": result, "diagnostics": [], "next_actions": []},
            }

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
                with patch.object(local_agent, "gateway_exchange", side_effect=fake_gateway):
                    result = run(args)
                run_dir = next((Path(temp) / "results").iterdir())
                events = [json.loads(line) for line in (run_dir / "tool-trace.jsonl").read_text(encoding="utf-8").splitlines()]
                prompt_states = [json.loads(line) for line in (run_dir / "prompt-states.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual(len(prompt_states), Handler.index)
                self.assertTrue(all(item["state_sha256"] == digest(item["state"]) for item in prompt_states))
                return result, gateway_calls, events, Handler.index
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_provider_double_repairs_unknown_operation_without_sending_it_to_gateway(self):
        result, gateway_calls, events, provider_calls = self._run_catalog_guard_provider_double([
            "get_item_by_normalized_name", "get_item"
        ])
        self.assertEqual(result["failure"], "AgentRunError:proposal_not_successfully_created")
        self.assertEqual(provider_calls, 4)
        self.assertEqual([call["arguments"].get("operation") for call in gateway_calls],
                         [None, "get_item"])
        self.assertEqual(events[1]["execution_origin"], "runner_prevalidation")
        self.assertEqual(events[1]["response"]["diagnostics"][0]["code"], "OPERATION_NOT_IN_CATALOG")
        self.assertEqual(events[2]["execution_origin"], "gateway")
        self.assertEqual(events[2]["response"]["ok"], True)

    def test_provider_double_stops_after_second_unknown_operation_name(self):
        result, gateway_calls, events, provider_calls = self._run_catalog_guard_provider_double([
            "get_item_by_normalized_name", "another_unknown_operation"
        ])
        self.assertEqual(result["failure"], "AgentRunError:operation_not_in_catalog")
        self.assertEqual(provider_calls, 3)
        self.assertEqual(len(gateway_calls), 1)
        self.assertNotIn("operation", gateway_calls[0]["arguments"])
        self.assertEqual(len(events), 3)
        self.assertEqual(events[1]["response"]["diagnostics"][0]["code"], "OPERATION_NOT_IN_CATALOG")
        self.assertEqual(events[2]["response"]["diagnostics"][0]["code"], "OPERATION_NOT_IN_CATALOG")
        self.assertTrue(all(event["execution_origin"] == "runner_prevalidation" for event in events[1:]))


    def test_compacted_conversation_preserves_exact_gateway_state_and_latest_diagnostics(self):
        base = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "user", "content": "tool schemas"},
        ]
        operation = copy.deepcopy(self.inspected_operations["get_item_by_name"])
        ordered_operations = {
            "get_job": copy.deepcopy(self.inspected_operations["get_job"]),
            "get_item_by_name": operation,
        }
        diagnostics = [{
            "code": "IR_PRESERVATION_MISMATCH",
            "message": "changed existing operation",
            "fix_hint": "Copy the exact inspected declaration",
        }]
        compacted = _compact_conversation(
            base,
            self.inspected,
            ordered_operations,
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
        ledger = json.loads(compacted[3]["content"].split("\n", 1)[1])
        self.assertEqual(ledger["service_inspection"], self.inspected)
        self.assertEqual(
            ledger["operation_inspections"]["get_item_by_name"],
            operation,
        )
        self.assertEqual(list(ledger["operation_inspections"]), ["get_job", "get_item_by_name"])
        self.assertEqual(ledger["tool_sequence"], ["service.inspect", "service.propose"])
        self.assertEqual(ledger["recent_tool_outcomes"][-1]["diagnostics"], diagnostics)
        self.assertEqual(ledger["recent_tool_outcomes"][-1]["next_actions"], ["Correct the complete IR"])
        self.assertNotIn("assistant", [item["role"] for item in compacted])
        self.assertNotIn("tool_calls", compacted[3]["content"])

    def test_compaction_ledger_is_deterministic_and_traceable(self):
        tool_sequence = ["service.inspect", "service.propose"]
        outcomes = [{"tool": "service.inspect", "ok": True}]
        first = _build_compaction_ledger(
            self.inspected, self.inspected_operations, tool_sequence, outcomes
        )
        second = _build_compaction_ledger(
            self.inspected, self.inspected_operations, tool_sequence, outcomes
        )
        self.assertEqual(first, second)
        self.assertEqual(digest(first), digest(second))
        self.assertEqual(first["service_inspection"], self.inspected)
        self.assertEqual(first["operation_inspections"], self.inspected_operations)
        self.assertEqual(first["tool_sequence"], tool_sequence)
        self.assertEqual(first["recent_tool_outcomes"], outcomes)

    def test_provider_chat_enforces_absolute_deadline_during_slow_drip_response(self):
        class SlowDripHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100")
                self.end_headers()
                try:
                    self.wfile.write(b"{")
                    self.wfile.flush()
                    for _ in range(99):
                        time.sleep(0.05)
                        self.wfile.write(b" ")
                        self.wfile.flush()
                except OSError:
                    return

            def log_message(self, *_args):
                return

        server = HTTPServer(("127.0.0.1", 0), SlowDripHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(AgentRunError, "provider_deadline_exceeded"):
                provider_chat(("127.0.0.1", server.server_port), {}, timeout=0.25)
            self.assertLess(time.monotonic() - started, 1.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


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

    def test_exhausted_proposal_budget_is_a_terminal_runner_condition(self):
        response = _proposal_budget_response({"request_id": "fourth-proposal"})
        self.assertTrue(_is_proposal_budget_exhausted(response))
        self.assertFalse(_is_proposal_budget_exhausted({
            "ok": False,
            "diagnostics": [{"code": "INSPECTION_INCOMPLETE"}],
        }))
        self.assertFalse(_is_proposal_budget_exhausted({"ok": True, "diagnostics": []}))


    def test_proposal_repair_budget_response_is_explicit_and_fail_closed(self):
        response = _proposal_budget_response({"request_id": "fourth-proposal"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "PROPOSAL_REPAIR_BUDGET_EXCEEDED")


    def test_catalog_operation_guard_allows_one_repair_and_stops_on_any_second_unknown_name(self):
        inspected = {"operations": [{"name": name} for name in (
            "cancel_job", "create_item", "get_item", "get_item_by_name", "get_job", "submit_rebuild"
        )]}
        attempts = set()
        first = {"request_id": "bad-op-1", "tool": "service.inspect",
                 "arguments": {"service_id": "catalog", "operation": "get_item_by_normalized_name"}}
        response, exhausted = prevalidate_catalog_operation(first, inspected, attempts)
        self.assertFalse(exhausted)
        self.assertEqual(response["diagnostics"][0]["code"], "OPERATION_NOT_IN_CATALOG")
        self.assertEqual(response["diagnostics"][0]["message"],
            "Operation 'get_item_by_normalized_name' not found. Available operations: "
            "[cancel_job, create_item, get_item, get_item_by_name, get_job, submit_rebuild]. "
            "If you want to create it, use service.propose instead.")
        known = {"tool": "service.inspect", "arguments": {"operation": "get_item"}}
        self.assertEqual(prevalidate_catalog_operation(known, inspected, attempts), (None, False))
        second = {"request_id": "bad-op-2", "tool": "service.inspect",
                  "arguments": {"service_id": "catalog", "operation": "another_unknown_name"}}
        response, exhausted = prevalidate_catalog_operation(second, inspected, attempts)
        self.assertTrue(exhausted)
        self.assertEqual(response["diagnostics"][0]["code"], "OPERATION_NOT_IN_CATALOG")




    def delta_fixture(self, base_disclosure="minimal"):
        changes = [{
            "kind": "add_operation",
            "operation": copy.deepcopy(EXPECTED_OPERATION),
        }]
        materialized = local_agent.materialize_add_operation(
            local_agent.canonical_json({
                "service_id": SERVICE_ID,
                "base_revision": self.inspected["revision"],
                "changes": changes,
            }),
            service_id=SERVICE_ID,
            current_service=self.ir,
            trusted_effects={"repository.read"},
            trusted_capabilities={"items.read"},
        )
        candidate = {
            "schema_version": 1,
            "task_id": TASK_ID,
            "service_id": SERVICE_ID,
            "base_revision": self.inspected["revision"],
            "change_set_id": materialized["change_set_id"],
            "proposal_mode": "delta",
            "intent_digest": materialized["intent_digest"],
            "materialized_ir_digest": materialized["materialized_ir_digest"],
            "changes": changes,
        }
        proposal = {
            "arguments": {
                "service_id": SERVICE_ID,
                "base_revision": self.inspected["revision"],
                "changes": changes,
            },
            "result": {
                "change_set_id": materialized["change_set_id"],
                "base_revision": self.inspected["revision"],
                "proposal_mode": "delta",
                "intent_digest": materialized["intent_digest"],
                "materialized_ir_digest": materialized["materialized_ir_digest"],
            },
        }
        validation = {"ok": True, "result": {"valid": True}}
        plan = {
            "ok": True,
            "result": {
                "valid": True, "will_mutate": False, "will_deploy": False,
                "effects": ["repository.read"],
            },
        }
        sequence = ["service.inspect"]
        inspected_operations = {}
        if base_disclosure in {"per_operation", "upfront_full"}:
            inspected_operations = copy.deepcopy(self.inspected_operations)
        if base_disclosure == "per_operation":
            sequence.extend(["service.inspect"] * len(self.inspected_operations))
        sequence.extend(["service.propose_delta", "service.validate", "service.plan"])
        return candidate, proposal, validation, plan, sequence, inspected_operations

    def test_accepts_delta_candidate_in_minimal_disclosure_treatment(self):
        values = self.delta_fixture("minimal")
        result = self.verify(
            *values[:5], inspected_operations=values[5],
            proposal_mode="delta", base_disclosure="minimal",
        )
        self.assertEqual(result["proposal_mode"], "delta")
        self.assertEqual(result["added_operation"], "get_item_by_normalized_name")
        self.assertFalse(result["applied"])

    def test_accepts_delta_candidate_after_per_operation_or_upfront_full_disclosure(self):
        for mode in ("per_operation", "upfront_full"):
            values = self.delta_fixture(mode)
            result = self.verify(
                *values[:5], inspected_operations=values[5],
                proposal_mode="delta", base_disclosure=mode,
            )
            self.assertEqual(result["proposal_mode"], "delta")


    def test_minimal_delta_verifier_rejects_disclosed_operation_contracts(self):
        values = self.delta_fixture("minimal")
        with self.assertRaisesRegex(AgentRunError, "minimal_disclosure_contract_leak"):
            self.verify(
                *values[:5], inspected_operations=self.inspected_operations,
                proposal_mode="delta", base_disclosure="minimal",
            )

    def test_delta_verifier_rejects_modified_intent_and_hash(self):
        values = list(self.delta_fixture("minimal"))
        values[0]["intent_digest"] = "0" * 64
        with self.assertRaisesRegex(AgentRunError, "candidate_delta_proposal_identity_mismatch"):
            self.verify(
                *values[:5], inspected_operations=values[5],
                proposal_mode="delta", base_disclosure="minimal",
            )
        values = list(self.delta_fixture("minimal"))
        values[0]["changes"][0]["operation"]["capability"] = "admin.root"
        with self.assertRaisesRegex(AgentRunError, "candidate_delta_does_not_match_task"):
            self.verify(
                *values[:5], inspected_operations=values[5],
                proposal_mode="delta", base_disclosure="minimal",
            )


if __name__ == "__main__":
    unittest.main()
