from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "issue-title-convention.md"
AGENTS = ROOT / "AGENTS.md"
V1_PLAN = ROOT / "docs" / "V1_PLAN.md"


class IssueTitleConventionTests(unittest.TestCase):
    def test_public_guide_defines_canonical_format_and_allowed_types(self):
        guide = GUIDE.read_text(encoding="utf-8")
        self.assertIn("<type>(<scope>): <short, clear description>", guide)
        for issue_type in (
            "feat", "fix", "docs", "refactor", "test",
            "build", "ci", "chore", "perf", "revert",
        ):
            with self.subTest(issue_type=issue_type):
                self.assertRegex(guide, rf"`{issue_type}`")

    def test_scope_and_metadata_rules_are_explicit(self):
        guide = GUIDE.read_text(encoding="utf-8")
        self.assertRegex(guide, r"lowercase kebab-case scope")
        for metadata in ("priority", "milestone", "task/feature/command IDs",
                         "agent identity", "run metadata"):
            with self.subTest(metadata=metadata):
                self.assertIn(metadata, guide)
        self.assertIn("Task: Txx", guide)

    def test_agent_instructions_link_to_repository_owned_guidance(self):
        agents = AGENTS.read_text(encoding="utf-8")
        self.assertIn("docs/issue-title-convention.md", agents)
        self.assertNotIn("mojtaba-arvin/commands", agents)

    def test_v1_task_ids_stay_in_issue_bodies_and_branch_contract_is_preserved(self):
        plan = V1_PLAN.read_text(encoding="utf-8")
        self.assertIn("put the `Txx` identifier in the Issue body", plan)
        self.assertIn("Task: Txx", plan)
        self.assertIn("origin/research/reboot-core", plan)
        self.assertNotIn('title `[Txx] ...`', plan)


if __name__ == "__main__":
    unittest.main()
