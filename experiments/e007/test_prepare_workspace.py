import json
import tempfile
import unittest
from pathlib import Path

from prepare_workspace import prepare_workspace


class WorkspacePreparationTests(unittest.TestCase):
    def test_workspace_contains_only_one_task_and_no_oracle_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "agent-workspace"
            result = prepare_workspace("tenant-isolation", destination)
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                {"TASK.md", "workspace-manifest.json"},
            )
            prompt = (destination / "TASK.md").read_text(encoding="utf-8")
            self.assertIn("tenant A", prompt)
            self.assertNotIn("idempotency", prompt)
            self.assertNotIn("tenant-isolation-v1", prompt)
            self.assertFalse(result["oracle_material_included"])
            saved = json.loads((destination / "workspace-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["prompt_sha256"], result["prompt_sha256"])

    def test_unknown_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unknown_or_ambiguous"):
                prepare_workspace("not-a-task", Path(directory) / "workspace")

    def test_nonempty_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "workspace"
            destination.mkdir()
            sentinel = destination / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must_be_missing_or_empty"):
                prepare_workspace("tenant-isolation", destination)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_invalid_task_path_syntax_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "invalid_task_id"):
                prepare_workspace("../tenant-isolation", Path(directory) / "workspace")


if __name__ == "__main__":
    unittest.main()
