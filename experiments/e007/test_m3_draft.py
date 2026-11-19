from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAFT_PATH = ROOT / "experiments" / "e007" / "m3-cohort-draft.json"


class M3DraftSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.draft = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))

    def test_draft_is_explicitly_non_executable_and_unregistered(self):
        self.assertEqual(self.draft["status"], "draft")
        self.assertFalse(self.draft["preregistered"])
        self.assertFalse(self.draft["execution_allowed"])
        self.assertTrue(self.draft["no_apply"])
        self.assertEqual(self.draft["schema_version"], 1)
        preregistrations = json.loads(
            (ROOT / "project-control" / "PREREGISTRATIONS.json").read_text(encoding="utf-8")
        )
        prereg_text = json.dumps(preregistrations)
        self.assertNotIn(self.draft["cohort_id"], prereg_text)

    def test_three_public_task_prompts_exist_and_are_unique(self):
        tasks = self.draft["tasks"]
        ids = [task["task_id"] for task in tasks]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)
        for task in tasks:
            path = ROOT / task["public_task"]
            self.assertTrue(path.is_file(), task["public_task"])
            self.assertIn("**Status:** draft", path.read_text(encoding="utf-8"))
            self.assertIn("separate evaluator sandbox", task["oracle_location"])

    def test_provider_cost_and_runner_gates_remain_unset(self):
        self.assertEqual(self.draft["model_tiers"], {"strong": None, "medium": None, "weak": None})
        self.assertIsNone(self.draft["model_provider"])
        self.assertIsNone(self.draft["immutable_model_versions"])
        self.assertIsNone(self.draft["repetitions_per_cell"])
        self.assertIsNone(self.draft["randomized_order"])
        self.assertIsNone(self.draft["per_run_cost_ceiling_usd"])
        self.assertIsNone(self.draft["cohort_cost_ceiling_usd"])
        self.assertIsNone(self.draft["runner"]["kind"])
        self.assertIsNone(self.draft["runner"]["image_digest"])
        self.assertFalse(self.draft["evaluator_isolation"]["implemented"])
        self.assertTrue(self.draft["evaluator_isolation"]["required"])
        self.assertTrue(self.draft["evaluator_isolation"]["scaffolded"])

    def test_evaluator_scaffold_contains_no_oracle_fixture(self):
        evaluator_dir = ROOT / "experiments" / "e007" / "evaluator"
        names = {path.name for path in evaluator_dir.iterdir() if path.is_file()}
        self.assertTrue({"__init__.py", "README.md", "OWNER_SETUP.md", "boundary.py", "test_boundary.py"}.issubset(names))
        self.assertNotIn("oracle.json", names)

    def test_no_provider_secrets_are_embedded_in_the_draft(self):
        serialized = json.dumps(self.draft).lower()
        for secret_field in ("api_key", "access_token", "secret_key", "password"):
            self.assertNotIn(secret_field, serialized)


if __name__ == "__main__":
    unittest.main()
