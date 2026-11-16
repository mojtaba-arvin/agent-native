import copy
import json
import unittest

from gateway import MAX_MESSAGE_BYTES, PilotGateway
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
        self.assertEqual(progressive["surface"]["disclosure_arm"], "progressive")
        self.assertEqual(upfront["surface"]["disclosure_arm"], "upfront")

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
