from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from validate_factorial_dispatch import DispatchValidationError, validate_dispatch


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).parent / "dispatch.json"


class FactorialDispatchTests(unittest.TestCase):
    def _copy_fixture(self, temporary: str) -> tuple[Path, Path]:
        root = Path(temporary)
        eval_dir = root / "experiments" / "e007" / "evals"
        eval_dir.mkdir(parents=True)
        (root / "experiments" / "e009").mkdir(parents=True)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for item in manifest["cases"]:
            source = ROOT / item["case_path"]
            shutil.copy2(source, eval_dir / source.name)
        target_manifest = root / "experiments" / "e007" / "dispatch.json"
        target_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return root, target_manifest

    def test_checked_in_manifest_validates_as_four_matched_cells(self):
        manifest, rows = validate_dispatch(ROOT, MANIFEST)
        self.assertEqual(manifest["status"], "ready_for_manual_dispatch")
        self.assertTrue(manifest["no_apply"])
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            {(row["proposal_mode"], row["base_disclosure"]) for row in rows},
            {
                ("snapshot", "per_operation"),
                ("delta", "per_operation"),
                ("snapshot", "upfront_full"),
                ("delta", "upfront_full"),
            },
        )
        self.assertEqual(
            [(row["proposal_mode"], row["base_disclosure"]) for row in rows],
            [
                ("snapshot", "upfront_full"),
                ("snapshot", "per_operation"),
                ("delta", "upfront_full"),
                ("delta", "per_operation"),
            ],
        )

    def test_case_eval_id_must_match_manifest_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_path = self._copy_fixture(temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["cases"][0]["eval_id"] = "different-eval-id"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DispatchValidationError, "identity_or_settings_mismatch"):
                validate_dispatch(root, manifest_path)

    def test_duplicate_factorial_cell_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_path = self._copy_fixture(temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["cases"][1]["proposal_mode"] = manifest["cases"][0]["proposal_mode"]
            manifest["cases"][1]["base_disclosure"] = manifest["cases"][0]["base_disclosure"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DispatchValidationError, "duplicate"):
                validate_dispatch(root, manifest_path)


    def test_execution_order_must_be_a_complete_pre_registered_permutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_path = self._copy_fixture(temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["execution_order"] = ["A", "A", "C", "D"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DispatchValidationError, "execution_order_invalid"):
                validate_dispatch(root, manifest_path)


    def test_randomization_seed_must_reproduce_the_recorded_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_path = self._copy_fixture(temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["randomization_seed"] += 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DispatchValidationError, "execution_order_invalid"):
                validate_dispatch(root, manifest_path)

    def test_model_budget_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_path = self._copy_fixture(temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["model_settings"]["max_input_tokens"] += 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DispatchValidationError, "model_or_budget_changed"):
                validate_dispatch(root, manifest_path)


    def test_pilot_shell_entrypoint_passes_bash_syntax_check(self):
        script = Path(__file__).parent / "run_factorial_pilot.sh"
        completed = subprocess.run(
            ["bash", "-n", str(script)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_dispatch_cannot_enable_apply_or_unapproved_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, manifest_path = self._copy_fixture(temporary)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["no_apply"] = False
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(DispatchValidationError, "no_apply_policy"):
                validate_dispatch(root, manifest_path)


if __name__ == "__main__":
    unittest.main()
