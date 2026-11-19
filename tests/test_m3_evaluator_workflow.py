from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_DIR = ROOT / "experiments" / "e007" / "evaluator"
sys.path.insert(0, str(EVALUATOR_DIR))

from agent_stub import write_candidate
from boundary import EvaluatorBoundaryError
from evaluator_job import evaluate_candidate
from sandbox_probe import SandboxProbeError, parse_cpu_quota, parse_positive_limit, validate_sandbox_report


class SandboxProbeUnitTests(unittest.TestCase):
    def _valid_report(self):
        return {
            "effective_uid": 1001,
            "root_read_only": True,
            "tmp_noexec": True,
            "no_new_privileges": True,
            "effective_capabilities_hex": "0",
            "outbound_network_blocked": True,
            "memory_limit_bytes": 2 * 1024**3,
            "cpu_quota_cores": 1.0,
            "pids_limit": 64,
            "output_mount_writable": True,
        }

    def test_parses_cgroup_limits(self):
        self.assertEqual(parse_positive_limit("2147483648", "memory.max"), 2147483648)
        self.assertEqual(parse_cpu_quota("50000 100000"), 0.5)

    def test_rejects_unbounded_or_malformed_cgroup_limits(self):
        with self.assertRaises(SandboxProbeError):
            parse_positive_limit("max", "pids.max")
        with self.assertRaises(SandboxProbeError):
            parse_cpu_quota("max 100000")

    def test_validates_runtime_sandbox_attestation_fail_closed(self):
        report = self._valid_report()
        validate_sandbox_report(report)
        report["outbound_network_blocked"] = False
        with self.assertRaises(SandboxProbeError):
            validate_sandbox_report(report)

    def test_evaluator_score_contains_both_sandbox_attestations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "agent-output"
            output = root / "evaluator-output" / "score.json"
            report = self._valid_report()
            candidate_path, _ = write_candidate(workspace, report)
            score = evaluate_candidate(workspace, candidate_path, output, sandbox_report=report)
            self.assertEqual(score["agent_sandbox"], report)
            self.assertEqual(score["evaluator_sandbox"], report)
            self.assertNotIn("oracle_path", score)


class M3EvaluatorTopologyTests(unittest.TestCase):
    def test_deterministic_agent_stub_emits_no_apply_candidate_and_trace(self):
        with tempfile.TemporaryDirectory() as temp:
            candidate_path, trace_path = write_candidate(temp)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertTrue(candidate["no_apply"])
            self.assertFalse(candidate["apply_invoked"])
            hashes = {candidate["phases"][phase]["candidate_sha256"] for phase in ("proposal", "validation", "plan")}
            self.assertEqual(len(hashes), 1)
            self.assertEqual(trace["candidate_sha256"], next(iter(hashes)))

    def test_evaluator_uses_private_synthetic_oracle_and_emits_only_public_score(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "agent-output"
            output = root / "evaluator-output" / "score.json"
            candidate_path, _ = write_candidate(workspace)
            score = evaluate_candidate(workspace, candidate_path, output)
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(score["passed"])
            self.assertEqual(score, persisted)
            self.assertFalse(score["oracle_path_disclosed"])
            self.assertFalse(score["oracle_contents_disclosed"])
            self.assertNotIn("oracle_path", score)
            self.assertNotIn("oracle", score)

    def test_evaluator_rejects_candidate_payload_changed_after_hashing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "agent-output"
            candidate_path, _ = write_candidate(workspace)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["candidate"]["value"]["quantity"] = 999
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaises(EvaluatorBoundaryError):
                evaluate_candidate(workspace, candidate_path, root / "score.json")

    def test_evaluator_rejects_symlink_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "agent-output"
            candidate_path, _ = write_candidate(workspace)
            symlink = workspace / "candidate-link.json"
            symlink.symlink_to(candidate_path)
            with self.assertRaises(EvaluatorBoundaryError):
                evaluate_candidate(workspace, symlink, root / "score.json")

    def test_evaluator_rejects_apply_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "agent-output"
            candidate_path, _ = write_candidate(workspace)
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            candidate["apply_invoked"] = True
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
            with self.assertRaises(EvaluatorBoundaryError):
                evaluate_candidate(workspace, candidate_path, root / "score.json")


class M3WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / ".github" / "workflows" / "m3-evaluator.yml").read_text(encoding="utf-8")

    def _job_block(self, name: str) -> str:
        match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)", self.workflow)
        self.assertIsNotNone(match, f"missing workflow job: {name}")
        return match.group(1)

    def test_workflow_is_limited_to_research_push_or_manual_smoke(self):
        trigger = self.workflow.split("jobs:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        self.assertIn("push:", trigger)
        self.assertIn("research/reboot-core", trigger)
        self.assertNotIn("pull_request:", trigger)
        self.assertNotIn("schedule:", trigger)
        guard = self._job_block("guard")
        self.assertIn("workflow_dispatch|push", guard)
        self.assertIn("refs/heads/research/reboot-core", guard)
        self.assertIn("topology-smoke", guard)

    def test_agent_job_has_no_oracle_or_evaluator_environment_access(self):
        agent_job = self._job_block("agent")
        self.assertNotIn("environment:", agent_job)
        self.assertNotIn("secrets.", agent_job)
        self.assertNotIn("oracle", agent_job.lower())
        self.assertIn("candidate.json", agent_job)
        self.assertIn("trace.jsonl", agent_job)
        self.assertIn("dst=/evaluator,readonly", agent_job)
        self.assertIn("python /evaluator/agent_stub.py", agent_job)

    def test_evaluator_is_separate_and_is_the_only_environment_job(self):
        evaluator_job = self._job_block("evaluator")
        self.assertIn("needs: agent", evaluator_job)
        self.assertIn("environment:", evaluator_job)
        self.assertIn("name: m3-evaluator", evaluator_job)
        self.assertIn("score.json", evaluator_job)
        self.assertNotIn("oracle.json", evaluator_job)

    def test_both_sandboxes_are_resource_limited_and_network_is_disabled(self):
        self.assertEqual(self.workflow.count("--network none"), 2)
        for required in ("--memory=2g", "--cpus=1", "--pids-limit=64", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges"):
            self.assertIn(required, self.workflow)
        self.assertIn("python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b", self.workflow)
        self.assertIn("verify_sandbox", (EVALUATOR_DIR / "sandbox_probe.py").read_text(encoding="utf-8"))

    def test_workflow_artifacts_are_allowlisted_and_short_lived(self):
        self.assertIn("m3-agent-output", self.workflow)
        self.assertIn("m3-evaluator-score", self.workflow)
        self.assertIn("retention-days: 1", self.workflow)
        self.assertNotIn("oracle.json", self.workflow)

    def test_topology_smoke_has_no_provider_or_oracle_secrets(self):
        for secret_name in ("M3_ORACLE_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "secrets."):
            self.assertNotIn(secret_name, self.workflow)
        self.assertEqual(self.workflow.count("environment:"), 1)


if __name__ == "__main__":
    unittest.main()
