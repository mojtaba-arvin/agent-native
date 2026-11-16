import copy
import json
import unittest

from gateway import MAX_MESSAGE_BYTES, JsonlTraceSink, PilotGateway
from surface import assert_fair_pair, build_surface


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = PilotGateway("progressive")

    def call(self, tool, arguments, request_id="pilot-1"):
        return self.gateway.handle_message({
            "type": "tool_call",
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        })

    def test_session_uses_the_requested_disclosure_arm(self):
        progressive = PilotGateway("progressive").session_message()
        upfront = PilotGateway("upfront").session_message()
        assert_fair_pair(progressive["surface"], upfront["surface"])
        self.assertNotIn("disclosure_arm", progressive["surface"])
        self.assertNotIn("disclosure_arm", upfront["surface"])
        progressive_schema_count = sum(
            "input_schema" in item for item in progressive["surface"]["tools"]
        )
        upfront_schema_count = sum(
            "input_schema" in item for item in upfront["surface"]["tools"]
        )
        self.assertEqual(progressive_schema_count, 1)
        self.assertEqual(upfront_schema_count, len(upfront["surface"]["tools"]))

    def test_progressive_discovery_returns_a_complete_tool_schema(self):
        listed = self.call("interface.describe", {})
        self.assertTrue(listed["response"]["ok"])
        names = {item["name"] for item in listed["response"]["result"]["tools"]}
        self.assertIn("service.propose", names)

        detailed = self.call("interface.describe", {"name": "service.propose"})
        self.assertTrue(detailed["response"]["ok"])
        schema = detailed["response"]["result"]["input_schema"]
        self.assertEqual(schema["type"], "object")
        self.assertEqual(
            set(schema["required"]),
            {"service_id", "base_revision", "ir"},
        )

    def test_unknown_tools_are_rejected_without_dispatch(self):
        response = self.call("shell.exec", {"command": "id"})
        self.assertFalse(response["response"]["ok"])
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "UNKNOWN_TOOL",
        )

    def test_disabled_apply_never_changes_the_service(self):
        before = self.gateway.interface.revision("catalog")
        response = self.call("service.apply", {"change_set_id": "not-a-real-change"})
        after = self.gateway.interface.revision("catalog")
        self.assertFalse(response["response"]["ok"])
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "APPLY_DISABLED",
        )
        self.assertEqual(before, after)

    def test_gateway_rejects_unknown_envelope_fields(self):
        response = self.gateway.handle_message({
            "type": "tool_call",
            "request_id": "r1",
            "tool": "interface.describe",
            "arguments": {},
            "debug": True,
        })
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "REQUEST_FIELDS",
        )

    def test_gateway_rejects_non_object_arguments(self):
        response = self.call("service.inspect", ["catalog"])
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "ARGUMENT_SHAPE",
        )

    def test_gateway_rejects_invalid_request_ids(self):
        response = self.call("interface.describe", {}, request_id="")
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "REQUEST_ID",
        )

    def test_gateway_rejects_duplicate_json_keys(self):
        raw = (
            b'{"type":"tool_call","request_id":"r1","tool":"interface.describe",'
            b'"arguments":{},"arguments":{}}\n'
        )
        response = json.loads(self.gateway.handle_line(raw))
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "DUPLICATE_JSON_KEY",
        )

    def test_gateway_rejects_non_finite_numbers(self):
        raw = (
            b'{"type":"tool_call","request_id":"r1","tool":"service.propose",'
            b'"arguments":{"ir":{"v":NaN}}}\n'
        )
        response = json.loads(self.gateway.handle_line(raw))
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "NON_FINITE_JSON_NUMBER",
        )

    def test_gateway_rejects_invalid_utf8(self):
        response = json.loads(self.gateway.handle_line(b"\xff\n"))
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "INVALID_UTF8",
        )

    def test_gateway_rejects_oversized_messages(self):
        response = json.loads(self.gateway.handle_line(b" " * (MAX_MESSAGE_BYTES + 1)))
        self.assertEqual(
            response["response"]["diagnostics"][0]["code"],
            "MESSAGE_TOO_LARGE",
        )

    def test_trace_sink_records_run_identity_surface_and_tool_failures(self):
        events = []
        gateway = PilotGateway(
            "progressive",
            trace_sink=events.append,
            trace_context={
                "run_id": "trial-001",
                "candidate_id": "progressive",
                "model_id": "model-test",
                "task_id": "pilot-catalog-add-readonly-operation",
                "attempt": 1,
            },
        )
        self.assertEqual(events[0]["event_type"], "task_started")
        self.assertEqual(events[1]["event_type"], "runtime_metric")
        self.assertEqual(events[1]["metric_name"], "initial_surface_payload")
        self.assertEqual(events[1]["metric_unit"], "bytes")

        gateway.handle_message({
            "type": "tool_call",
            "request_id": "r1",
            "tool": "interface.describe",
            "arguments": {"name": "service.inspect"},
        })
        gateway.handle_message({
            "type": "tool_call",
            "request_id": "r2",
            "tool": "not.a.real.tool",
            "arguments": {},
        })
        calls = [event for event in events if event["event_type"] == "tool_call"]
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["tool_name"], "interface.describe")
        self.assertTrue(calls[0]["schema_lookup"])
        self.assertNotIn("failure_class", calls[0])
        self.assertEqual(calls[1]["failure_class"], "UNKNOWN_TOOL")
        self.assertTrue(all(event["run_id"] == "trial-001" for event in events))
        self.assertTrue(all(event["candidate_id"] == "progressive" for event in events))
        self.assertTrue(all(event["model_id"] == "model-test" for event in events))

    def test_trace_sink_requires_complete_identity(self):
        with self.assertRaisesRegex(ValueError, "trace_context_missing_required_identity"):
            PilotGateway("progressive", trace_sink=lambda _event: None, trace_context={})

    def test_jsonl_trace_sink_creates_exclusive_private_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            sink = JsonlTraceSink(path)
            sink({"event_id": "e1", "event_type": "task_started"})
            sink.close()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "event_id": "e1",
                "event_type": "task_started",
            })
            with self.assertRaises(FileExistsError):
                JsonlTraceSink(path)

    def test_successful_proposal_hash_is_written_to_trace_without_ir_body(self):
        events = []
        gateway = PilotGateway(
            "upfront",
            trace_sink=events.append,
            trace_context={
                "run_id": "proposal-trial",
                "candidate_id": "upfront",
                "model_id": "model-test",
                "task_id": "pilot-catalog-add-readonly-operation",
                "attempt": 1,
            },
        )
        base_revision = gateway.interface.revision("catalog")
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
        response = gateway.handle_message({
            "type": "tool_call",
            "request_id": "propose-1",
            "tool": "service.propose",
            "arguments": {
                "service_id": "catalog",
                "base_revision": base_revision,
                "ir": proposed_ir,
            },
        })
        self.assertTrue(response["response"]["ok"])
        proposal_events = [
            event for event in events
            if event["event_type"] == "tool_call"
            and event["tool_name"] == "service.propose"
        ]
        self.assertEqual(len(proposal_events), 1)
        self.assertEqual(
            proposal_events[0]["change_set_id"],
            response["response"]["result"]["change_set_id"],
        )
        self.assertNotIn("ir", proposal_events[0])
        self.assertNotIn("arguments", proposal_events[0])

        change_set_id = response["response"]["result"]["change_set_id"]
        validation = gateway.handle_message({
            "type": "tool_call",
            "request_id": "validate-1",
            "tool": "service.validate",
            "arguments": {"change_set_id": change_set_id},
        })
        plan = gateway.handle_message({
            "type": "tool_call",
            "request_id": "plan-1",
            "tool": "service.plan",
            "arguments": {"change_set_id": change_set_id},
        })
        self.assertTrue(validation["response"]["result"]["valid"])
        self.assertTrue(plan["response"]["result"]["valid"])
        lifecycle_events = [
            event for event in events
            if event["event_type"] == "tool_call"
            and event["tool_name"] in {"service.validate", "service.plan"}
        ]
        self.assertEqual(len(lifecycle_events), 2)
        self.assertTrue(all(event["change_set_id"] == change_set_id for event in lifecycle_events))
        self.assertTrue(all("arguments" not in event and "ir" not in event for event in lifecycle_events))


    def test_task_change_is_representable_and_does_not_mutate_service(self):
        # This deterministic fixture checks that E-005 can express the task.
        # It is not an LLM/agent trial and is not the hidden acceptance oracle.
        inspected = self.call("service.inspect", {"service_id": "catalog"})
        self.assertTrue(inspected["response"]["ok"])
        base_revision = inspected["response"]["result"]["revision"]

        proposed_ir = copy.deepcopy(self.gateway.interface.services["catalog"])
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
        original_revision = self.gateway.interface.revision("catalog")

        proposed = self.call("service.propose", {
            "service_id": "catalog",
            "base_revision": base_revision,
            "ir": proposed_ir,
        })
        self.assertTrue(proposed["response"]["ok"])
        change_set_id = proposed["response"]["result"]["change_set_id"]

        validated = self.call("service.validate", {"change_set_id": change_set_id})
        self.assertTrue(validated["response"]["ok"])
        self.assertTrue(validated["response"]["result"]["valid"])

        plan = self.call("service.plan", {"change_set_id": change_set_id})
        self.assertTrue(plan["response"]["ok"])
        self.assertTrue(plan["response"]["result"]["valid"])
        self.assertIn("repository.read", plan["response"]["result"]["effects"])
        self.assertEqual(
            set(plan["response"]["result"]["effects"]),
            {"repository.read", "repository.write"},
        )
        self.assertFalse(plan["response"]["result"]["will_mutate"])
        self.assertFalse(plan["response"]["result"]["will_deploy"])
        self.assertEqual(
            self.gateway.interface.revision("catalog"),
            original_revision,
        )


if __name__ == "__main__":
    unittest.main()
