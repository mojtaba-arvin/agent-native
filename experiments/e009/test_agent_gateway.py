from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from agent_gateway import AgentNativeGateway
from kernel import load_service_ir
from surface import assert_fair_pair, build_surface


PILOT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = (Path(__file__).parent / "catalog.an").read_text(encoding="utf-8")


class AgentGatewayTests(unittest.TestCase):
    def setUp(self):
        self.progressive = AgentNativeGateway("progressive")
        self.upfront = AgentNativeGateway("upfront")

    def call(self, gateway, request_id, tool, arguments):
        result = gateway.handle_message({
            "type": "tool_call",
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        })
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["request_id"], request_id)
        return result["response"]

    def test_both_agent_arms_use_same_dispatch_and_tool_identity(self):
        assert_fair_pair(
            build_surface("progressive"),
            build_surface("upfront"),
        )
        progressive = self.progressive.session_message()["surface"]
        upfront = self.upfront.session_message()["surface"]
        self.assertEqual(progressive["dispatch"], upfront["dispatch"])
        self.assertEqual(
            [(item["name"], item["summary"], item["mode"]) for item in progressive["tools"]],
            [(item["name"], item["summary"], item["mode"]) for item in upfront["tools"]],
        )

    def test_progressive_discovery_returns_named_operation_schema(self):
        progressive_names = {
            item["name"]: item for item in self.progressive.session_message()["surface"]["tools"]
        }
        upfront_names = {
            item["name"]: item for item in self.upfront.session_message()["surface"]["tools"]
        }
        self.assertNotIn("input_schema", progressive_names["service.propose"])
        self.assertIn("input_schema", upfront_names["service.propose"])

        described = self.call(
            self.progressive,
            "describe-propose-001",
            "interface.describe",
            {"name": "service.propose"},
        )
        self.assertTrue(described["ok"])
        self.assertIn("input_schema", described["result"])

    def test_agent_can_inspect_propose_validate_and_plan_live_service(self):
        inspected = self.call(
            self.progressive,
            "inspect-001",
            "service.inspect",
            {"service_id": "catalog"},
        )
        self.assertTrue(inspected["ok"])
        self.assertEqual(inspected["result"]["service"]["name"], "Catalog")
        base_revision = inspected["result"]["revision"]

        candidate_ir = load_service_ir(SOURCE)
        blocked = self.call(
            self.progressive,
            "propose-before-full-inspection",
            "service.propose",
            {
                "service_id": "catalog",
                "base_revision": base_revision,
                "ir": candidate_ir,
            },
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["diagnostics"][0]["code"], "INSPECTION_INCOMPLETE")
        self.assertEqual(
            blocked["next_actions"],
            [
                f"service.inspect with operation={name}"
                for name in sorted(item["name"] for item in candidate_ir["operations"])
            ],
        )
        for operation in candidate_ir["operations"]:
            inspected_operation = self.call(
                self.progressive,
                f"inspect-{operation['name']}",
                "service.inspect",
                {"service_id": "catalog", "operation": operation["name"]},
            )
            self.assertTrue(inspected_operation["ok"])

        candidate_ir["operations"].append({
            "name": "get_item_by_status",
            "method": "GET",
            "path": "/items/by-status/{name}",
            "input": [{"name": "name", "type": "String", "source": "path"}],
            "output": "Item",
            "errors": ["InvalidInput", "NotFound", "Unauthorized"],
            "validation": ["name.non_empty"],
            "effects": ["repository.read"],
            "capability": "items.read",
        })

        proposed = self.call(
            self.progressive,
            "propose-001",
            "service.propose",
            {
                "service_id": "catalog",
                "base_revision": base_revision,
                "ir": candidate_ir,
            },
        )
        self.assertTrue(proposed["ok"])
        change_set_id = proposed["result"]["change_set_id"]
        validated = self.call(
            self.progressive,
            "validate-001",
            "service.validate",
            {"change_set_id": change_set_id},
        )
        self.assertTrue(validated["ok"])
        self.assertTrue(validated["result"]["valid"])
        planned = self.call(
            self.progressive,
            "plan-001",
            "service.plan",
            {"change_set_id": change_set_id},
        )
        self.assertTrue(planned["ok"])
        self.assertTrue(planned["result"]["valid"])
        self.assertFalse(planned["result"]["will_mutate"])
        self.assertFalse(planned["result"]["will_deploy"])

        applied = self.call(
            self.progressive,
            "apply-001",
            "service.apply",
            {"change_set_id": change_set_id},
        )
        self.assertFalse(applied["ok"])
        self.assertEqual(applied["diagnostics"][0]["code"], "APPLY_DISABLED")

        current = self.call(
            self.progressive,
            "inspect-after-proposal",
            "service.inspect",
            {"service_id": "catalog"},
        )
        self.assertEqual(
            len(current["result"]["operations"]),
            len(load_service_ir(SOURCE)["operations"]),
        )

    def test_repeated_service_inspection_redirects_to_uninspected_operation_without_resetting_progress(self):
        first = self.call(
            self.upfront, "inspect-service", "service.inspect", {"service_id": "catalog"}
        )
        self.assertTrue(first["ok"])
        operation_names = [item["name"] for item in first["result"]["operations"]]
        expected_actions = [
            f"service.inspect with operation={name}" for name in operation_names
        ]
        self.assertEqual(first["next_actions"], expected_actions)

        repeated = self.call(
            self.upfront, "repeat-service-inspect", "service.inspect", {"service_id": "catalog"}
        )
        self.assertFalse(repeated["ok"])
        self.assertEqual(repeated["diagnostics"][0]["code"], "INSPECTION_OPERATION_REQUIRED")
        self.assertEqual(repeated["next_actions"], expected_actions)

        first_operation = self.call(
            self.upfront,
            "inspect-first-operation",
            "service.inspect",
            {"service_id": "catalog", "operation": operation_names[0]},
        )
        self.assertTrue(first_operation["ok"])
        repeated_again = self.call(
            self.upfront, "repeat-after-one-operation", "service.inspect", {"service_id": "catalog"}
        )
        self.assertFalse(repeated_again["ok"])
        self.assertEqual(
            repeated_again["next_actions"],
            [f"service.inspect with operation={name}" for name in operation_names[1:]],
        )

        for name in operation_names[1:]:
            result = self.call(
                self.upfront,
                f"inspect-{name}",
                "service.inspect",
                {"service_id": "catalog", "operation": name},
            )
            self.assertTrue(result["ok"])

        complete = self.call(
            self.upfront, "repeat-after-complete-inspection", "service.inspect",
            {"service_id": "catalog"},
        )
        self.assertTrue(complete["ok"])
        self.assertEqual(
            complete["next_actions"],
            ["service.propose with the inspected base_revision and complete canonical IR snapshot"],
        )
        self.assertEqual(
            self.upfront._inspected_operations,
            set(operation_names),
        )

    def test_stale_revision_and_unknown_tools_are_rejected(self):
        inspected = self.call(
            self.progressive, "inspect-002", "service.inspect", {"service_id": "catalog"}
        )
        ir = load_service_ir(SOURCE)
        stale = self.call(
            self.progressive,
            "stale-proposal",
            "service.propose",
            {
                "service_id": "catalog",
                "base_revision": "0" * 64,
                "ir": ir,
            },
        )
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["diagnostics"][0]["code"], "STALE_BASE_REVISION")
        self.assertEqual(inspected["result"]["revision"], self.progressive.interface.revision("catalog"))

        unknown = self.call(
            self.progressive, "unknown-001", "shell.execute", {"command": "whoami"}
        )
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["diagnostics"][0]["code"], "UNKNOWN_TOOL")

    def test_duplicate_keys_and_non_finite_json_are_rejected_at_process_boundary(self):
        duplicate = self.progressive.handle_line(
            b'{"type":"tool_call","request_id":"x","tool":"service.inspect","tool":"shell.execute","arguments":{}}\n'
        )
        duplicate_result = json.loads(duplicate)
        self.assertFalse(duplicate_result["response"]["ok"])
        self.assertEqual(duplicate_result["response"]["diagnostics"][0]["code"], "DUPLICATE_JSON_KEY")

        non_finite = self.progressive.handle_line(
            b'{"type":"tool_call","request_id":"x","tool":"service.inspect","arguments":{"service_id":NaN}}\n'
        )
        non_finite_result = json.loads(non_finite)
        self.assertFalse(non_finite_result["response"]["ok"])
        self.assertEqual(non_finite_result["response"]["diagnostics"][0]["code"], "NON_FINITE_JSON_NUMBER")

    def test_cli_process_emits_session_and_dispatches_live_tool_call(self):
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("agent_gateway.py")),
                "--arm",
                "progressive",
            ],
            cwd=REPOSITORY_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            session = json.loads(process.stdout.readline())
            self.assertEqual(session["type"], "session")
            self.assertEqual(session["surface"]["dispatch"]["name"], "agent.invoke")
            request = {
                "type": "tool_call",
                "request_id": "process-inspect-001",
                "tool": "service.inspect",
                "arguments": {"service_id": "catalog"},
            }
            process.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertEqual(response["type"], "tool_result")
            self.assertTrue(response["response"]["ok"])
            self.assertEqual(response["response"]["result"]["service"]["name"], "Catalog")
        finally:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            process.wait(timeout=10)
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            self.assertEqual(process.returncode, 0, stderr)
            for stream in (process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()



    def _inspect_complete_catalog(self, gateway, prefix="preserve"):
        inspected = self.call(
            gateway, f"{prefix}-service", "service.inspect", {"service_id": "catalog"}
        )
        self.assertTrue(inspected["ok"])
        for item in inspected["result"]["operations"]:
            response = self.call(
                gateway,
                f"{prefix}-{item['name']}",
                "service.inspect",
                {"service_id": "catalog", "operation": item["name"]},
            )
            self.assertTrue(response["ok"])
        return inspected["result"]

    def test_gateway_rejects_proposal_that_rewrites_an_existing_operation(self):
        inspected = self._inspect_complete_catalog(self.progressive, "rewrite")
        ir = load_service_ir(SOURCE)
        ir["operations"].append({
            "name": "get_item_by_status",
            "method": "GET",
            "path": "/items/by-status/{name}",
            "input": [{"name": "name", "type": "String", "source": "path"}],
            "output": "Item",
            "errors": ["InvalidInput", "NotFound", "Unauthorized"],
            "validation": ["name.non_empty"],
            "effects": ["repository.read"],
            "capability": "items.read",
        })
        existing = next(item for item in ir["operations"] if item["name"] == "cancel_job")
        existing["capability"] = "jobs.read"
        response = self.call(
            self.progressive,
            "rewrite-existing",
            "service.propose",
            {
                "service_id": "catalog",
                "base_revision": inspected["revision"],
                "ir": ir,
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "IR_PRESERVATION_MISMATCH")
        self.assertIn("cancel_job", response["diagnostics"][0]["message"])
        self.assertIn("capability", response["diagnostics"][0]["fix_hint"])

    def test_gateway_rejects_changed_service_identity_or_types(self):
        inspected = self._inspect_complete_catalog(self.progressive, "identity")
        ir = load_service_ir(SOURCE)
        ir["service"]["version"] = "99"
        response = self.call(
            self.progressive,
            "changed-service",
            "service.propose",
            {
                "service_id": "catalog",
                "base_revision": inspected["revision"],
                "ir": ir,
            },
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["diagnostics"][0]["code"], "IR_PRESERVATION_MISMATCH")
        self.assertIn("service", response["diagnostics"][0]["message"])

if __name__ == "__main__":
    unittest.main()
