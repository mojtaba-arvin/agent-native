import copy
import unittest
from pathlib import Path

from agent_native import Parser
from interface import AgentInterface


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "e001" / "examples" / "catalog.an").read_text(encoding="utf-8")
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
        self.assertFalse(response["result"]["applied"])
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


if __name__ == "__main__":
    unittest.main()
