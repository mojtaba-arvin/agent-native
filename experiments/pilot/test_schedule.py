import copy
import unittest

from schedule import (
    ARMS,
    ScheduleError,
    resolve_git_revision,
    verify_schedule_checkout,
    create_schedule,
    validate_schedule,
)


class ScheduleTests(unittest.TestCase):
    def build(self, **overrides):
        arguments = {
            "pairs": 10,
            "seed": 20261116,
            "model_id": "provider/model-version-pinned",
            "source_revision": "a" * 40,
            "max_input_tokens": 16000,
            "max_output_tokens": 4000,
            "max_tool_calls": 40,
            "max_wall_seconds": 900,
            "generation_settings": {
                "temperature": 0,
                "top_p": 1,
                "response_format": "json",
            },
        }
        arguments.update(overrides)
        return create_schedule(**arguments)

    def test_schedule_is_deterministic_for_same_seed_and_inputs(self):
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        validate_schedule(first)

    def test_each_pair_contains_both_arms_once(self):
        schedule = self.build(pairs=30)
        self.assertEqual(len(schedule["trials"]), 60)
        for index in range(30):
            pair = schedule["trials"][index * 2:index * 2 + 2]
            self.assertEqual({trial["candidate_id"] for trial in pair}, set(ARMS))
            self.assertEqual(pair[1]["sequence"], pair[0]["sequence"] + 1)

    def test_model_settings_and_budgets_are_identical_for_every_trial(self):
        schedule = self.build()
        for trial in schedule["trials"]:
            self.assertEqual(
                trial["generation_settings"],
                schedule["protocol"]["generation_settings"],
            )
            self.assertEqual(trial["budgets"], schedule["protocol"]["budgets"])
            self.assertEqual(trial["model_id"], schedule["protocol"]["model_id"])

    def test_arm_label_is_out_of_band_and_never_agent_visible(self):
        schedule = self.build()
        self.assertFalse(schedule["protocol"]["execution"]["agent_receives_arm_label"])
        for trial in schedule["trials"]:
            self.assertFalse(trial["agent_visible_treatment_label"])

    def test_source_files_are_content_hashed(self):
        schedule = self.build()
        hashes = schedule["protocol"]["source_sha256"]
        self.assertIn("experiments/pilot/TASK.md", hashes)
        self.assertIn("experiments/e005/tools.json", hashes)
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))

    def test_run_ids_are_unique_and_bound_to_plan_pair_and_arm(self):
        import hashlib

        schedule = self.build()
        ids = [trial["run_id"] for trial in schedule["trials"]]
        self.assertEqual(len(ids), len(set(ids)))
        for trial in schedule["trials"]:
            pair_number = int(trial["pair_id"].split("-")[1])
            digest = hashlib.sha256(
                f"{schedule['plan_id']}:{pair_number}:{trial['candidate_id']}".encode()
            ).hexdigest()
            expected = f"{trial['pair_id']}-{trial['candidate_id']}-{digest[:12]}"
            self.assertEqual(trial["run_id"], expected)

    def test_reordered_trial_entries_are_rejected(self):
        schedule = self.build()
        tampered = copy.deepcopy(schedule)
        tampered["trials"][0], tampered["trials"][1] = (
            tampered["trials"][1], tampered["trials"][0]
        )
        with self.assertRaisesRegex(ScheduleError, "trial_sequence_missing_or_duplicate"):
            validate_schedule(tampered)

    def test_git_revision_resolver_requires_a_clean_checkout(self):
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Pilot Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "pilot@example.invalid"], cwd=root, check=True)
            (root / "tracked.txt").write_text("pinned\\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "fixture"],
                cwd=root,
                check=True,
                env={**os.environ, "GIT_AUTHOR_DATE":"2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE":"2026-01-01T00:00:00Z"},
            )
            revision = resolve_git_revision(root)
            self.assertRegex(revision, r"^[0-9a-f]{40}$")
            (root / "untracked.txt").write_text("dirty\\n", encoding="utf-8")
            with self.assertRaisesRegex(ScheduleError, "working_tree_must_be_clean"):
                resolve_git_revision(root)

    def test_trial_metadata_does_not_alias_protocol_metadata(self):
        schedule = self.build()
        protocol_before = copy.deepcopy(schedule["protocol"])
        schedule["trials"][0]["budgets"]["max_tool_calls"] += 1
        schedule["trials"][0]["generation_settings"]["temperature"] = 0.7
        schedule["trials"][0]["source_sha256"]["experiments/pilot/TASK.md"] = "0" * 64
        self.assertEqual(schedule["protocol"], protocol_before)


    def test_schedule_verifies_against_exact_clean_checkout(self):
        revision = resolve_git_revision()
        schedule = self.build(source_revision=revision)
        verify_schedule_checkout(schedule)

    def test_schedule_rejects_another_source_revision(self):
        schedule = self.build(source_revision="a" * 40)
        with self.assertRaisesRegex(ScheduleError, "checkout_revision_does_not_match_schedule"):
            verify_schedule_checkout(schedule)


    def test_schedule_detects_budget_tampering(self):
        schedule = self.build()
        tampered = copy.deepcopy(schedule)
        tampered["trials"][0]["budgets"]["max_tool_calls"] += 1
        with self.assertRaisesRegex(ScheduleError, "trial_budget_mismatch"):
            validate_schedule(tampered)

    def test_schedule_detects_plan_metadata_tampering(self):
        schedule = self.build()
        tampered = copy.deepcopy(schedule)
        tampered["protocol"]["model_id"] = "different-model"
        with self.assertRaisesRegex(ScheduleError, "plan_id_mismatch"):
            validate_schedule(tampered)

    def test_schedule_detects_arm_label_leak(self):
        schedule = self.build()
        tampered = copy.deepcopy(schedule)
        tampered["trials"][0]["agent_visible_treatment_label"] = True
        with self.assertRaisesRegex(ScheduleError, "trial_arm_label_must_be_hidden"):
            validate_schedule(tampered)

    def test_schedule_detects_unbalanced_pair(self):
        schedule = self.build()
        tampered = copy.deepcopy(schedule)
        tampered["trials"][1]["candidate_id"] = tampered["trials"][0]["candidate_id"]
        pair_number = 1
        candidate_id = tampered["trials"][1]["candidate_id"]
        import hashlib
        run_hash = hashlib.sha256(
            f"{tampered['plan_id']}:{pair_number}:{candidate_id}".encode()
        ).hexdigest()
        tampered["trials"][1]["run_id"] = (
            f"pair-{pair_number:04d}-{candidate_id}-{run_hash[:12]}"
        )
        with self.assertRaisesRegex(ScheduleError, "trial_run_id_missing_or_duplicate"):
            validate_schedule(tampered)

    def test_credentials_are_rejected_from_generation_settings(self):
        with self.assertRaisesRegex(ScheduleError, "must_not_contain_credentials"):
            self.build(generation_settings={"nested": {"api_key": "must-not-be-stored"}})

    def test_non_finite_generation_settings_are_rejected(self):
        with self.assertRaisesRegex(ScheduleError, "must_be_finite_json"):
            self.build(generation_settings={"temperature": float("nan")})

    def test_invalid_pair_count_and_revision_are_rejected(self):
        with self.assertRaisesRegex(ScheduleError, "pairs_must_be_between"):
            self.build(pairs=0)
        with self.assertRaisesRegex(ScheduleError, "full_git_sha"):
            self.build(source_revision="short")


if __name__ == "__main__":
    unittest.main()
