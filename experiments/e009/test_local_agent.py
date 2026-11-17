from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))

from kernel import load_service_ir
from local_agent import (
    AgentRunError,
    EXPECTED_OPERATION,
    SERVICE_ID,
    TASK_ID,
    digest,
    validate_ollama_endpoint,
    verify_candidate,
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

    def verify(self, candidate, proposal, validation, plan, sequence, inspected_operations=None):
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
        )

    def test_accepts_exact_readonly_proposal_with_full_inspection(self):
        values = self.fixture()
        result = self.verify(*values)
        self.assertEqual(result["added_operation"], "get_item_by_normalized_name")
        self.assertEqual(result["validation"], "passed")
        self.assertEqual(result["plan"], "valid_no_mutation_no_deployment")

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
        values[4].remove("service.inspect")
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

    def test_ollama_endpoint_is_strictly_loopback_ip(self):
        self.assertEqual(validate_ollama_endpoint("http://127.0.0.1:11434"), ("127.0.0.1", 11434))
        with self.assertRaises(ValueError):
            validate_ollama_endpoint("http://example.com:11434")
        with self.assertRaises(ValueError):
            validate_ollama_endpoint("https://127.0.0.1:11434")
        with self.assertRaises(ValueError):
            validate_ollama_endpoint("http://127.0.0.1:11434/api/chat")


if __name__ == "__main__":
    unittest.main()
