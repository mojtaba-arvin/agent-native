import json
import tempfile
import unittest
from pathlib import Path

from schedule import ScheduleError, resolve_git_revision, create_schedule
from verify_schedule import load_schedule


class VerifyScheduleFileTests(unittest.TestCase):
    def test_load_schedule_reads_valid_json_object(self):
        schedule = create_schedule(
            pairs=1,
            seed=7,
            model_id="test-model",
            source_revision=resolve_git_revision(),
            max_input_tokens=1000,
            max_output_tokens=500,
            max_tool_calls=10,
            max_wall_seconds=120,
            generation_settings={"temperature": 0},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_text(json.dumps(schedule), encoding="utf-8")
            self.assertEqual(load_schedule(path), schedule)

    def test_duplicate_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_text('{"schedule_version":1,"schedule_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ScheduleError, "duplicate_key"):
                load_schedule(path)

    def test_non_finite_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_text('{"value":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ScheduleError, "non_finite"):
                load_schedule(path)

    def test_non_object_schedule_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_text('[]', encoding="utf-8")
            with self.assertRaisesRegex(ScheduleError, "must_be_object"):
                load_schedule(path)

    def test_oversized_schedule_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "schedule.json"
            path.write_bytes(b" " * (16 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ScheduleError, "too_large"):
                load_schedule(path)


if __name__ == "__main__":
    unittest.main()
