import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class CorpusTests(unittest.TestCase):
    def test_task_prompts_and_oracle_ids_are_complete(self):
        manifest = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "task_definitions_only")
        self.assertEqual(len(manifest["tasks"]), 10)
        self.assertTrue((ROOT / "TASKS.md").is_file())
        ids = [task["id"] for task in manifest["tasks"]]
        oracles = [task["oracle_id"] for task in manifest["tasks"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(oracles), len(set(oracles)))
        self.assertTrue(all(task["prompt_file"] == "TASKS.md" for task in manifest["tasks"]))


if __name__ == "__main__":
    unittest.main()
