import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "e001" / "prototype"))

from agent_native import Parser
from interface import AgentInterface

SOURCE = (ROOT / "experiments" / "e001" / "examples" / "catalog.an").read_text(encoding="utf-8")
IR = Parser(SOURCE).parse()
TRUSTED_EFFECTS = {"repository.read", "repository.write"}


class AgentInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.interface = AgentInterface({"catalog": IR}, trusted_effects=TRUSTED_EFFECTS)
        self.revision = self.interface.revision("catalog")

    def request(self, tool, arguments, request_id="req-1"):
        return self.interface.handle({
            "protocol_version": "0.1",
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        })

    def propose(self, ir=None):
        return self.request("service.propose", {
            "service_id": "catalog",
            "base_revision": self.revision,
            "ir": copy.deepcopy(IR if ir is None else ir),
        })

    def test_progressive_discovery_lists_compact_tools(self):
        response = self.request("interface.describe", {})
        self.assertTrue(response["ok"])
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("service.inspect", names)
        self.assertNotIn("shell.exec", names)
        self.assertNotIn("network.fetch", names)

    def test_inspect_returns_only_selected_operation(self):
        response = self.request("service.inspect", {
            "service_id": "catalog",
            "operation": "get_item",
        })
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["operation"]["name"], "get_item")

    def test_proposal_is_content_addressed_and_does_not_apply(self):
        first = self.propose()
        second = self.propose()
        self.assertTrue(first["ok"])
        self.assertEqual(
            first["result"]["change_set_id"],
            second["result"]["change_set_id"],
        )
        self.assertFalse(first["result"]["applied"])
        self.assertEqual(self.interface.revision("catalog"), self.revision)

    def test_stale_base_revision_is_rejected(self):
        response = self.request("service.propose", {
            "service_id": "catalog",
            "base_revision": "stale",
            "ir": IR,
        })
        self.assertEqual(response["diagnostics"][0]["code"], "STALE_BASE_REVISION")

    def test_validate_rejects_effect_outside_trusted_allowlist(self):
        changed = copy.deepcopy(IR)
        changed["operations"][0]["effects"].append("network.egress")
        proposal = self.propose(changed)
        change_set_id = proposal["result"]["change_set_id"]
        validated = self.request("service.validate", {"change_set_id": change_set_id})
        self.assertFalse(validated["result"]["valid"])
        self.assertEqual(validated["result"]["diagnostics"][0]["code"], "UNTRUSTED_EFFECT")

    def test_validate_uses_shared_ir_semantic_validator(self):
        changed = copy.deepcopy(IR)
        get_item = next(item for item in changed["operations"] if item["name"] == "get_item")
        get_item["path"] = "/items/../secrets"
        change_set_id = self.propose(changed)["result"]["change_set_id"]
        validated = self.request("service.validate", {"change_set_id": change_set_id})
        self.assertFalse(validated["result"]["valid"])
        self.assertEqual(validated["result"]["diagnostics"][0]["code"], "AN027")

    def test_plan_marks_high_impact_effect_for_human_approval(self):
        changed = copy.deepcopy(IR)
        changed["operations"][0]["effects"].append("network.egress")
        change_set_id = self.propose(changed)["result"]["change_set_id"]
        plan = self.request("service.plan", {"change_set_id": change_set_id})
        self.assertTrue(plan["result"]["human_approval_required"])
        self.assertIn("network.egress", plan["result"]["approval_reasons"])
        self.assertFalse(plan["result"]["will_mutate"])
        self.assertFalse(plan["result"]["will_deploy"])

    def test_apply_is_disabled_and_never_mutates(self):
        change_set_id = self.propose()["result"]["change_set_id"]
        before = self.interface.revision("catalog")
        response = self.request("service.apply", {"change_set_id": change_set_id})
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "APPLY_DISABLED")
        self.assertEqual(self.interface.revision("catalog"), before)

    def test_unknown_tool_has_stable_diagnostic(self):
        response = self.request("shell.exec", {"command": "echo unsafe"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "UNKNOWN_TOOL")

    def test_protocol_version_is_checked(self):
        response = self.interface.handle({
            "protocol_version": "99",
            "request_id": "req-x",
            "tool": "interface.describe",
            "arguments": {},
        })
        self.assertEqual(response["diagnostics"][0]["code"], "PROTOCOL_VERSION")



    def test_non_object_request_returns_diagnostic(self):
        response = self.interface.handle(["not", "an", "object"])
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "REQUEST_SHAPE")

    def test_unknown_envelope_and_tool_argument_fields_are_rejected(self):
        request = {
            "protocol_version": "0.1",
            "request_id": "req-extra",
            "tool": "service.inspect",
            "arguments": {"service_id": "catalog"},
            "debug": True,
        }
        response = self.interface.handle(request)
        self.assertEqual(response["diagnostics"][0]["code"], "REQUEST_FIELDS")
        response = self.request("service.inspect", {"service_id": "catalog", "include_secrets": True})
        self.assertEqual(response["diagnostics"][0]["code"], "ARGUMENT_FIELDS")

    def test_unhashable_service_identifiers_return_diagnostics(self):
        response = self.request("service.inspect", {"service_id": ["catalog"]})
        self.assertEqual(response["diagnostics"][0]["code"], "ARGUMENT_TYPE")

    def test_proposal_rejects_non_finite_json_values(self):
        changed = copy.deepcopy(IR)
        changed["service"]["version"] = float("nan")
        response = self.propose(changed)
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "INVALID_PROPOSAL")

    def test_plan_handles_malformed_ir_without_raising(self):
        changed = copy.deepcopy(IR)
        changed["operations"][0] = None
        proposal = self.propose(changed)
        change_set_id = proposal["result"]["change_set_id"]
        plan = self.request("service.plan", {"change_set_id": change_set_id})
        self.assertTrue(plan["ok"])
        self.assertFalse(plan["result"]["valid"])
        self.assertEqual(plan["result"]["validation_diagnostics"][0]["code"], "AN026")
        self.assertFalse(plan["result"]["will_mutate"])


    def test_service_propose_publishes_complete_ir_and_input_array_schema(self):
        response = self.request("interface.describe", {"name": "service.propose"})
        self.assertTrue(response["ok"])
        schema = response["result"]["input_schema"]["properties"]["ir"]
        self.assertEqual(
            schema["required"],
            ["ir_version", "service", "types", "operations"],
        )
        self.assertEqual(schema["properties"]["ir_version"]["enum"], [1])
        operation = schema["properties"]["operations"]["items"]
        self.assertEqual(operation["properties"]["input"]["type"], "array")
        declaration = operation["properties"]["input"]["items"]
        self.assertEqual(
            set(declaration["required"]),
            {"name", "source", "type"},
        )

    def test_an021_explains_full_ir_snapshot_and_version_requirement(self):
        changed = copy.deepcopy(IR)
        changed.pop("ir_version")
        proposal = self.propose(changed)
        self.assertTrue(proposal["ok"])
        validated = self.request(
            "service.validate",
            {"change_set_id": proposal["result"]["change_set_id"]},
        )
        self.assertFalse(validated["result"]["valid"])
        diagnostic = validated["result"]["diagnostics"][0]
        self.assertEqual(diagnostic["code"], "AN021")
        self.assertIn("ir_version", diagnostic["fix_hint"])
        self.assertIn("complete canonical IR snapshot", diagnostic["fix_hint"])
        self.assertIn("not a patch", diagnostic["fix_hint"])

if __name__ == "__main__":
    unittest.main()
