from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "e009"))
sys.path.insert(0, str(ROOT / "experiments" / "e005"))
sys.path.insert(0, str(ROOT / "experiments" / "e004"))
sys.path.insert(0, str(ROOT / "experiments" / "e010"))

from agent_gateway import AgentNativeGateway
from demo_apply import NEW_OPERATION, SandboxApplyCoordinator
from local_agent import verify_candidate


class SandboxApplyEndToEndTests(unittest.TestCase):
    def _call(self, gateway, tool, arguments, request_id):
        return gateway.handle_message({
            "type": "tool_call",
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        })["response"]

    def test_inspect_propose_validate_plan_apply_publishes_runtime_and_audit(self):
        with tempfile.TemporaryDirectory(prefix="agent-native-e010-") as temporary:
            coordinator = SandboxApplyCoordinator(Path(temporary) / "sandbox")
            gateway = AgentNativeGateway("upfront", apply_callback=coordinator.apply)
            self.assertTrue(any(
                item.get("name") == "service.apply" and item.get("mode") == "sandbox_only"
                for item in gateway.surface["tools"]
            ))

            inspected = self._call(gateway, "service.inspect", {"service_id": "catalog"}, "inspect-service")
            self.assertTrue(inspected["ok"])
            for operation in inspected["result"]["operations"]:
                result = self._call(
                    gateway, "service.inspect",
                    {"service_id": "catalog", "operation": operation["name"]},
                    f"inspect-{operation['name']}",
                )
                self.assertTrue(result["ok"])

            ir = copy.deepcopy(coordinator.initial_ir)
            ir["operations"].append(copy.deepcopy(NEW_OPERATION))
            proposal = self._call(gateway, "service.propose", {
                "service_id": "catalog",
                "base_revision": inspected["result"]["revision"],
                "ir": ir,
            }, "propose-new-operation")
            self.assertTrue(proposal["ok"])
            change_set_id = proposal["result"]["change_set_id"]

            validation = self._call(gateway, "service.validate", {"change_set_id": change_set_id}, "validate-change")
            self.assertTrue(validation["ok"])
            self.assertTrue(validation["result"]["valid"])

            plan = self._call(gateway, "service.plan", {"change_set_id": change_set_id}, "plan-change")
            self.assertTrue(plan["ok"])
            self.assertTrue(plan["result"]["valid"])
            self.assertTrue(plan["result"]["will_mutate"])
            self.assertFalse(plan["result"]["will_deploy"])
            self.assertTrue(plan["result"]["sandbox_only"])

            applied = self._call(gateway, "service.apply", {"change_set_id": change_set_id}, "apply-change")
            self.assertTrue(applied["ok"])
            self.assertTrue(applied["result"]["applied"])
            self.assertTrue(applied["result"]["sandbox_only"])
            self.assertEqual(applied["result"]["runtime_smoke_test"]["status_code"], 200)
            self.assertEqual(applied["result"]["runtime_smoke_test"]["body"]["data"]["name"], "blue-lamp")
            self.assertEqual(coordinator.applied_revision, gateway.interface.revision("catalog"))
            inspected_result = inspected["result"]
            inspected_operations = {
                item["name"]: copy.deepcopy(item)
                for item in coordinator.initial_ir["operations"]
            }
            candidate = {
                "schema_version": 1,
                "task_id": "e010-sandbox-apply-lifecycle",
                "service_id": "catalog",
                "base_revision": inspected_result["revision"],
                "change_set_id": change_set_id,
                "ir": ir,
            }
            verification = verify_candidate(
                candidate,
                inspected=inspected_result,
                inspected_operations=inspected_operations,
                successful_proposal={
                    "arguments": {"base_revision": inspected_result["revision"], "ir": ir},
                    "result": proposal["result"],
                },
                validation_result=validation,
                plan_result=plan,
                tool_sequence=(
                    ["service.inspect"]
                    + ["service.inspect"] * len(inspected_result["operations"])
                    + ["service.propose", "service.validate", "service.plan", "service.apply"]
                ),
                validation_change_set_id=change_set_id,
                plan_change_set_id=change_set_id,
                expected_task_id="e010-sandbox-apply-lifecycle",
                allow_sandbox_apply=True,
                apply_result=applied,
            )
            self.assertEqual(verification["plan"], "valid_sandbox_apply_no_deployment")
            self.assertTrue(verification["applied"])
            events = coordinator.audit_sink.list_events()
            self.assertTrue(any(event["operation"] == "service.apply" for event in events))
            self.assertTrue(any(
                event["operation"] == "get_item_by_normalized_name" and event["decision"] == "allow"
                for event in events
            ))

            replay = self._call(gateway, "service.apply", {"change_set_id": change_set_id}, "apply-replay")
            self.assertTrue(replay["ok"])
            self.assertTrue(replay["result"]["replayed"])
            self.assertEqual(len([event for event in coordinator.audit_sink.list_events()
                                  if event["operation"] == "service.apply"]), 1)

    def test_apply_without_validation_and_plan_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="agent-native-e010-") as temporary:
            coordinator = SandboxApplyCoordinator(Path(temporary) / "sandbox")
            gateway = AgentNativeGateway("upfront", apply_callback=coordinator.apply)
            inspected = self._call(gateway, "service.inspect", {"service_id": "catalog"}, "inspect-service")
            for operation in inspected["result"]["operations"]:
                self._call(gateway, "service.inspect",
                    {"service_id": "catalog", "operation": operation["name"]},
                    f"inspect-{operation['name']}")
            ir = copy.deepcopy(coordinator.initial_ir)
            ir["operations"].append(copy.deepcopy(NEW_OPERATION))
            proposal = self._call(gateway, "service.propose", {
                "service_id": "catalog",
                "base_revision": inspected["result"]["revision"],
                "ir": ir,
            }, "propose-change")
            result = self._call(gateway, "service.apply", {
                "change_set_id": proposal["result"]["change_set_id"],
            }, "apply-too-early")
            self.assertFalse(result["ok"])
            self.assertEqual(result["diagnostics"][0]["code"], "APPLY_REQUIRES_VALIDATED_PLAN")
            self.assertIsNone(coordinator.applied_revision)


if __name__ == "__main__":
    unittest.main()
