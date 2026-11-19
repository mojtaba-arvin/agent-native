from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from evaluator.boundary import EvaluatorBoundaryError, validate_candidate_continuity, verify_evaluator_boundary


class EvaluatorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.workspace = root / "agent-workspace"
        self.external = root / "evaluator-private"
        self.workspace.mkdir()
        self.external.mkdir(mode=0o700)
        self.candidate = self.workspace / "candidate.json"
        self.candidate.write_text('{"candidate":"safe"}', encoding="utf-8")
        self.oracle = self.external / "oracle.json"
        self.oracle.write_text('{"expected":"private"}', encoding="utf-8")
        if os.name == "posix":
            self.external.chmod(0o700)
            self.oracle.chmod(0o600)

    def test_external_owner_only_oracle_and_workspace_candidate_are_accepted(self):
        evidence = verify_evaluator_boundary(self.workspace, self.candidate, self.oracle)
        self.assertEqual(len(evidence.candidate_sha256), 64)
        self.assertTrue(evidence.public_summary()["oracle_external_to_workspace"])
        self.assertFalse(evidence.public_summary()["oracle_path_disclosed"])
        self.assertFalse(hasattr(evidence, "oracle_path"))

    def test_oracle_inside_agent_workspace_is_rejected(self):
        oracle = self.workspace / "oracle.json"
        oracle.write_text("{}" , encoding="utf-8")
        if os.name == "posix":
            oracle.chmod(0o600)
        with self.assertRaises(EvaluatorBoundaryError):
            verify_evaluator_boundary(self.workspace, self.candidate, oracle)

    def test_candidate_outside_agent_workspace_is_rejected(self):
        with self.assertRaises(EvaluatorBoundaryError):
            verify_evaluator_boundary(self.workspace, self.oracle, self.oracle)

    def test_group_or_world_readable_oracle_is_rejected(self):
        if os.name == "posix":
            self.oracle.chmod(0o644)
            with self.assertRaises(EvaluatorBoundaryError):
                verify_evaluator_boundary(self.workspace, self.candidate, self.oracle)

    def test_oracle_in_group_or_world_accessible_directory_is_rejected(self):
        if os.name == "posix":
            self.external.chmod(0o755)
            with self.assertRaises(EvaluatorBoundaryError):
                verify_evaluator_boundary(self.workspace, self.candidate, self.oracle)

    def test_oracle_with_additional_hard_link_is_rejected(self):
        if os.name == "posix":
            alias = self.workspace / "oracle-alias.json"
            try:
                os.link(self.oracle, alias)
            except (OSError, NotImplementedError):
                self.skipTest("hard links are unavailable on this filesystem")
            with self.assertRaises(EvaluatorBoundaryError):
                verify_evaluator_boundary(self.workspace, self.candidate, self.oracle)

    def test_oracle_owned_by_another_user_is_rejected(self):
        if os.name == "posix":
            from unittest.mock import patch

            with patch("evaluator.boundary.os.geteuid", return_value=self.oracle.stat().st_uid + 1):
                with self.assertRaises(EvaluatorBoundaryError):
                    verify_evaluator_boundary(self.workspace, self.candidate, self.oracle)

    def test_symlink_oracle_is_rejected(self):
        link = self.external / "oracle-link.json"
        link.symlink_to(self.oracle)
        with self.assertRaises(EvaluatorBoundaryError):
            verify_evaluator_boundary(self.workspace, self.candidate, link)

    def test_symlink_candidate_is_rejected(self):
        link = self.workspace / "candidate-link.json"
        link.symlink_to(self.candidate)
        with self.assertRaises(EvaluatorBoundaryError):
            verify_evaluator_boundary(self.workspace, link, self.oracle)

    def test_proposal_validation_and_plan_must_share_candidate_hash(self):
        digest = "a" * 64
        candidate = {
            "no_apply": True,
            "phases": {
                "proposal": {"candidate_sha256": digest},
                "validation": {"candidate_sha256": digest},
                "plan": {"candidate_sha256": digest},
            },
        }
        self.assertEqual(validate_candidate_continuity(candidate), digest)
        candidate["phases"]["plan"]["candidate_sha256"] = "b" * 64
        with self.assertRaises(EvaluatorBoundaryError):
            validate_candidate_continuity(candidate)

    def test_apply_is_forbidden(self):
        digest = "a" * 64
        candidate = {
            "no_apply": True,
            "apply_invoked": True,
            "phases": {phase: {"candidate_sha256": digest} for phase in ("proposal", "validation", "plan")},
        }
        with self.assertRaises(EvaluatorBoundaryError):
            validate_candidate_continuity(candidate)


if __name__ == "__main__":
    unittest.main()
