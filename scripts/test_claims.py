"""Regression tests for evidence-backed completion claims."""
from __future__ import annotations

import json
import unittest

from check_claims import validate_claims


class ClaimsValidationTests(unittest.TestCase):
    def setUp(self):
        self.event = {
            "event_id": "RUN-1",
            "timestamp": "2026-11-19",
            "task_id": "CP-007",
            "kind": "workflow_validation",
            "outcome": "all_layers_passed_on_pr_head",
            "evidence": [{"run_id": 44424340406, "head_sha": "d2e47a9ddeb5e766958ad53b4e77c9bf1db92280"}],
        }
        self.progress = {
            "completion_claims": [{
                "id": "CLAIM-1",
                "statement": "Layer 0 and Layer 1 passed on the PR head.",
                "status": "verified",
                "evidence_event_ids": ["RUN-1"],
            }]
        }
        self.ledger = json.dumps(self.event)

    def test_accepts_claim_with_successful_immutable_evidence(self):
        self.assertEqual(validate_claims(self.progress, self.ledger), [])

    def test_rejects_claim_without_evidence(self):
        self.progress["completion_claims"][0]["evidence_event_ids"] = []
        self.assertTrue(any("at least one evidence_event_id" in e for e in validate_claims(self.progress, self.ledger)))

    def test_rejects_unknown_event(self):
        self.progress["completion_claims"][0]["evidence_event_ids"] = ["MISSING"]
        self.assertTrue(any("unknown evidence event" in e for e in validate_claims(self.progress, self.ledger)))

    def test_rejects_failed_or_ineligible_event(self):
        self.event["outcome"] = "failed"
        self.ledger = json.dumps(self.event)
        self.assertTrue(any("non-acceptance outcome" in e for e in validate_claims(self.progress, self.ledger)))

    def test_rejects_event_without_immutable_reference(self):
        self.event["evidence"] = [{"path": "REPORT.md"}]
        self.ledger = json.dumps(self.event)
        self.assertTrue(any("no immutable" in e for e in validate_claims(self.progress, self.ledger)))

    def test_rejects_duplicate_event_ids(self):
        self.ledger = json.dumps(self.event) + "\n" + json.dumps(self.event)
        self.assertTrue(any("duplicate event_id" in e for e in validate_claims(self.progress, self.ledger)))

    def test_rejects_malformed_ledger_line(self):
        self.ledger += "\n{not-json"
        self.assertTrue(any("invalid JSON" in e for e in validate_claims(self.progress, self.ledger)))

    def test_rejects_duplicate_claim_ids(self):
        self.progress["completion_claims"].append(dict(self.progress["completion_claims"][0]))
        self.assertTrue(any("duplicate claim id" in e for e in validate_claims(self.progress, self.ledger)))


if __name__ == "__main__":
    unittest.main()
