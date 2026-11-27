from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS_PATH = ROOT / "experiments" / "e004" / "requirements.json"


class SecurityRequirementTraceabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(REQUIREMENTS_PATH.read_text(encoding="utf-8"))
        cls.requirements = cls.document["requirements"]
        cls.gates = set(cls.document["human_approval_gates"])

    def test_every_requirement_maps_to_tests_or_an_explicit_human_gate(self):
        identifiers = [item["id"] for item in self.requirements]
        self.assertEqual(len(identifiers), len(set(identifiers)))

        for requirement in self.requirements:
            with self.subTest(requirement=requirement["id"]):
                tests = requirement.get("tests", [])
                gate = requirement.get("human_approval_gate")
                self.assertTrue(
                    tests or gate,
                    f'{requirement["id"]} has neither executable tests nor a human gate',
                )
                if gate:
                    self.assertIn(gate, self.gates)
                production_gate = requirement.get("production_gate")
                if production_gate:
                    self.assertIn(production_gate, self.gates)

    def test_every_test_reference_resolves_to_an_executable_test_method(self):
        for requirement in self.requirements:
            for reference in requirement.get("tests", []):
                with self.subTest(requirement=requirement["id"], reference=reference):
                    path, symbol = reference.split("::", 1)
                    method = symbol.rsplit(".", 1)[-1]
                    source_path = ROOT / path
                    self.assertTrue(source_path.is_file(), f"missing test file: {path}")
                    source = source_path.read_text(encoding="utf-8")
                    self.assertRegex(
                        source,
                        rf"(?m)^\s*def\s+{re.escape(method)}\s*\(",
                        f"missing executable test method: {reference}",
                    )

    def test_production_execution_apply_and_deployment_remain_disabled(self):
        for flag in (
            "production_enforcement_enabled",
            "production_execution_enabled",
            "apply_enabled",
            "production_deployment_enabled",
        ):
            with self.subTest(flag=flag):
                self.assertIs(self.document[flag], False)


if __name__ == "__main__":
    unittest.main()
