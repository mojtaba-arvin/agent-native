import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class EvidenceContractTests(unittest.TestCase):
    def test_substrate_comparison_does_not_promote_reference_to_production_choice(self):
        comparison = json.loads((ROOT / "substrate_comparison.json").read_text())
        self.assertEqual(comparison["production_substrate_decision"], "deferred")
        self.assertEqual(comparison["classification"],
                         "supported_architecture_comparison_not_benchmark")
        names = {candidate["name"] for candidate in comparison["candidates"]}
        self.assertTrue({"SQLite WAL", "PostgreSQL", "MySQL InnoDB"} <= names)
        for candidate in comparison["candidates"]:
            self.assertEqual(candidate["production_qualification"], "not_established")
            self.assertTrue(candidate["sources"])
        self.assertGreaterEqual(len(comparison["required_measurements_before_selection"]), 8)

    def test_evidence_claims_use_explicit_status_and_retain_limitations(self):
        evidence = json.loads((ROOT / "evidence.json").read_text())
        allowed = {"observed", "supported", "hypothesis", "decision", "rejected"}
        self.assertTrue(evidence["claims"])
        self.assertTrue(all(claim["status"] in allowed for claim in evidence["claims"]))
        self.assertTrue(evidence["limitations"])
        selection = next(
            claim for claim in evidence["claims"]
            if claim["id"] == "production-persistence-choice"
        )
        self.assertEqual(selection["status"], "decision")
        self.assertIn("No production persistence substrate", selection["statement"])


if __name__ == "__main__":
    unittest.main()
