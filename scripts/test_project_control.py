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
        task_by_id["M1-001"]["status"] = "in_progress"
        task_by_id["CP-007"]["status"] = "pending"
        with self.assertRaisesRegex(
            CONTROL["ControlPlaneError"], "incomplete dependencies"
        ):
            CONTROL["build_resume_checkpoint"](
                docs, (ROOT / "project-control" / "HANDOFF.md").read_text(encoding="utf-8")
            )




class SchedulerPlanTests(unittest.TestCase):
    @staticmethod
    def _docs(*, active=None, limit=2, tasks=None):
        return {
            "state": {"active_task_ids": list(active or []), "wip_limit": limit},
            "tasks": {"tasks": tasks or []},
            "roadmap": {"milestones": [{"id": "C2", "status": "in_progress"}]},
            "policy": {"recovery": {"unchanged_failure_limit": 2, "no_progress_attempt_limit": 3}},
        }

    @staticmethod
    def _task(task_id, *, status="ready", deps=None, execution=True, priority=1):
        task = {
            "id": task_id, "title": task_id, "milestone": "C2", "status": status,
            "depends_on": list(deps or []), "priority": priority, "acceptance": ["done"],
        }
        if execution:
            task["execution"] = {
                "branch": f"feat/{task_id.lower()}",
                "base_branch": "research/reboot-core",
                "integration_owner": "integrator",
            }
        return task

    @staticmethod
    def _events(*items):
        return "\n".join(json.dumps({
            "event_id": f"attempt-{index}", "timestamp": f"2026-11-19T00:0{index}:00Z",
            "task_id": "T1", "kind": "task_attempt", **item,
        }) for index, item in enumerate(items, 1))

    def test_selects_only_ready_tasks_with_complete_dependencies_and_execution_owner(self):
        tasks = [
            self._task("DONE", status="complete"),
            self._task("T1", deps=["DONE"]),
            self._task("T2", deps=["T1"]),
            self._task("T3", execution=False),
        ]
        plan = CONTROL["build_schedule_plan"](self._docs(active=["ACTIVE"], tasks=tasks), "")
        self.assertEqual([task["id"] for task in plan["selected_tasks"]], ["T1"])
        reasons = {item["task_id"]: item["reason"] for item in plan["deferred_tasks"]}
        self.assertEqual(reasons["T2"], "dependencies_incomplete:T1")
        self.assertEqual(reasons["T3"], "execution_metadata_missing")
        self.assertEqual(plan["selected_tasks"][0]["execution"]["integration_owner"], "integrator")

    def test_scheduler_never_exceeds_wip_limit(self):
        tasks = [self._task("T1"), self._task("T2", priority=2)]
        plan = CONTROL["build_schedule_plan"](self._docs(active=["A", "B"], limit=2, tasks=tasks), "")
        self.assertEqual(plan["available_slots"], 0)
        self.assertEqual(plan["selected_tasks"], [])

    def test_repeated_identical_failures_force_replan_and_are_not_retried(self):
        task = self._task("T1")
        ledger = self._events(
            {"outcome": "failed", "failure_signature": "same-root-cause"},
            {"outcome": "failed", "failure_signature": "same-root-cause"},
        )
        plan = CONTROL["build_schedule_plan"](self._docs(tasks=[task]), ledger)
        self.assertEqual(plan["selected_tasks"], [])
        self.assertEqual(plan["replan_required"][0]["reason"], "unchanged_failure_limit")
        self.assertEqual(plan["replan_required"][0]["required_action"], "stop_retries_record_root_cause_and_replan")

    def test_changed_failure_signature_resets_unchanged_failure_streak(self):
        task = self._task("T1")
        ledger = self._events(
            {"outcome": "failed", "failure_signature": "root-cause-a"},
            {"outcome": "failed", "failure_signature": "root-cause-b"},
        )
        plan = CONTROL["build_schedule_plan"](self._docs(tasks=[task]), ledger)
        self.assertEqual([item["id"] for item in plan["selected_tasks"]], ["T1"])
        self.assertEqual(plan["replan_required"], [])

    def test_no_progress_limit_forces_replan(self):
        task = self._task("T1")
        ledger = self._events(
            {"outcome": "no_progress"},
            {"outcome": "no_progress"},
            {"outcome": "no_progress"},
        )
        plan = CONTROL["build_schedule_plan"](self._docs(tasks=[task]), ledger)
        self.assertEqual(plan["selected_tasks"], [])
        self.assertEqual(plan["replan_required"][0]["reason"], "no_progress_attempt_limit")

    def test_scheduler_is_deterministic_and_does_not_mutate_state(self):
        docs = self._docs(tasks=[self._task("T2", priority=2), self._task("T1", priority=1)])
        before = json.dumps(docs, sort_keys=True)
        first = CONTROL["build_schedule_plan"](docs, "")
        second = CONTROL["build_schedule_plan"](docs, "")
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(docs, sort_keys=True), before)
        self.assertFalse(first["mutates_repository_state"])

    def test_schedule_command_emits_machine_readable_checkpoint(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "project_control.py"), "schedule"],
            cwd=ROOT, check=True, capture_output=True, text=True, timeout=10,
        )
        plan = json.loads(result.stdout)
        self.assertEqual(plan["status"], "ready")
        self.assertLessEqual(
            len(plan["selected_tasks"]) + len(plan["active_task_ids"]),
            plan["wip_limit"],
        )
        self.assertFalse(plan["mutates_repository_state"])


if __name__ == "__main__":
    unittest.main()
