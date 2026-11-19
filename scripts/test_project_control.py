from __future__ import annotations

import json
import runpy
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = runpy.run_path(str(ROOT / "project_control.py"))


class ResumeCheckpointTests(unittest.TestCase):
    def test_resume_command_emits_machine_readable_checkpoint(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "project_control.py"), "resume"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        checkpoint = json.loads(result.stdout)
        self.assertEqual(checkpoint["status"], "ready")
        self.assertIn("active_tasks", checkpoint)
        self.assertIn("next_action", checkpoint)
        self.assertLessEqual(len(checkpoint["active_tasks"]), checkpoint["wip_limit"])

    def test_resume_rejects_active_task_with_incomplete_dependency(self):
        docs, _ledger = CONTROL["load_documents"]()
        task_by_id = {item["id"]: item for item in docs["tasks"]["tasks"]}
        state = docs["state"]
        state["active_task_ids"] = ["M1-001"]
        task_by_id["CP-007"]["status"] = "pending"
        with self.assertRaisesRegex(
            CONTROL["ControlPlaneError"], "incomplete dependencies"
        ):
            CONTROL["build_resume_checkpoint"](
                docs, (ROOT / "project-control" / "HANDOFF.md").read_text(encoding="utf-8")
            )


if __name__ == "__main__":
    unittest.main()
