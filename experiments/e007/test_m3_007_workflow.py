import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "m3-007-alternative-models.yml"


def job_block(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        source,
    )
    if not match:
        raise AssertionError(f"workflow job {name!r} is missing")
    return match.group(1)


class M3007WorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")

    def test_static_validation_is_a_real_job(self):
        block = job_block(self.source, "static-validation")
        self.assertIn("runs-on: ubuntu-latest", block)
        self.assertIn("test_m3_alt_model_cohort.py", block)
        self.assertIn("test_m3_007_workflow.py", block)

    def test_cohort_waits_for_static_validation_and_dispatch_guard(self):
        block = job_block(self.source, "cohort")
        needs = re.search(r"(?m)^    needs:\s*(.+)$", block)
        self.assertIsNotNone(needs, "cohort must declare job dependencies")
        dependencies = {
            item.strip()
            for item in needs.group(1).strip().strip("[]").split(",")
        }
        self.assertEqual(dependencies, {"static-validation", "guard"})
        self.assertIn("if: needs.guard.outputs.allowed == 'true'", block)

    def test_guard_allows_only_manual_dispatch_on_canonical_branch(self):
        block = job_block(self.source, "guard")
        self.assertIn('GITHUB_EVENT_NAME" == "workflow_dispatch"', block)
        self.assertIn('GITHUB_REF" == "refs/heads/research/reboot-core"', block)
        self.assertIn('echo "allowed=false"', block)

    def test_push_cannot_enable_the_model_cohort(self):
        block = job_block(self.source, "cohort")
        guard = job_block(self.source, "guard")
        self.assertIn("needs: [static-validation, guard]", block)
        self.assertIn("GITHUB_EVENT_NAME", guard)
        self.assertIn("workflow_dispatch", guard)


if __name__ == "__main__":
    unittest.main()
