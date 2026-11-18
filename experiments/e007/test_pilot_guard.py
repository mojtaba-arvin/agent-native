from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pilot_guard import cohort_abort_reason


class PilotGuardTests(unittest.TestCase):
    def _write(self, directory: str, value: object) -> Path:
        path = Path(directory) / "result.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_provider_failure_stops_remaining_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, {
                "failure_categories": {"provider_http_error": 1}
            })
            self.assertEqual(
                cohort_abort_reason(path),
                "shared_infrastructure_failure:provider_http_error",
            )

    def test_runner_failure_stops_remaining_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, {
                "failure_categories": {"runner_or_gateway_error": 1}
            })
            self.assertEqual(
                cohort_abort_reason(path),
                "shared_infrastructure_failure:runner_or_gateway_error",
            )

    def test_agent_task_failure_does_not_stop_matched_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, {
                "failure_categories": {"agent_or_runner_failure": 1,
                                       "validation_rejection": 1}
            })
            self.assertIsNone(cohort_abort_reason(path))

    def test_resource_ceiling_is_not_automatically_an_infrastructure_abort(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, {
                "failure_categories": {"resource_budget_exceeded": 1}
            })
            self.assertIsNone(cohort_abort_reason(path))

    def test_missing_or_malformed_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            self.assertEqual(cohort_abort_reason(missing), "result_artifact_missing")
            malformed = Path(directory) / "bad.json"
            malformed.write_text("{", encoding="utf-8")
            self.assertEqual(cohort_abort_reason(malformed), "result_artifact_unreadable")

    def test_missing_failure_taxonomy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(directory, {"accepted_runs": 0})
            self.assertEqual(cohort_abort_reason(path), "failure_categories_missing")


if __name__ == "__main__":
    unittest.main()
