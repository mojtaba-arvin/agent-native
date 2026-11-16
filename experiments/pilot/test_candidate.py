import copy
import json
import tempfile
import unittest
from pathlib import Path

from candidate import (
    CandidateError,
    canonical_digest,
    load_candidate,
    load_trace_proposal_ids,
    validate_candidate,
)
from gateway import PilotGateway


class CandidateTests(unittest.TestCase):
    def setUp(self):
        gateway = PilotGateway("upfront")
        self.base_revision = gateway.interface.revision("catalog")
        ir = copy.deepcopy(gateway.interface.services["catalog"])
        ir["operations"].append({
            "name": "get_item_by_name",
            "method": "GET",
            "path": "/items/by-name/{name}",
            "input": [{"name": "name", "type": "String", "source": "path"}],
            "output": "Item",
            "errors": ["InvalidInput", "NotFound", "Unauthorized"],
            "validation": ["name.non_empty"],
            "effects": ["repository.read"],
            "capability": "items.read",
        })
        proposal = {
            "service_id": "catalog",
            "base_revision": self.base_revision,
            "ir": ir,
        }
        self.candidate = {
            "schema_version": 1,
            "task_id": "pilot-catalog-add-readonly-operation",
            "service_id": "catalog",
            "base_revision": self.base_revision,
            "change_set_id": canonical_digest(proposal),
            "ir": ir,
        }

    def test_valid_candidate_matches_its_content_address(self):
        summary = validate_candidate(
            self.candidate,
            traced_change_set_ids={self.candidate["change_set_id"]},
        )
        self.assertEqual(summary["service_id"], "catalog")
        self.assertEqual(summary["operation_count"], 3)

    def test_candidate_must_be_correlated_with_a_successful_proposal_trace(self):
        with self.assertRaisesRegex(CandidateError, "candidate_proposal_not_present_in_trace"):
            validate_candidate(self.candidate, traced_change_set_ids=set())

    def test_candidate_change_set_hash_is_recomputed(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["ir"]["operations"][0]["path"] = "/items/changed"
        with self.assertRaisesRegex(CandidateError, "candidate_change_set_id_mismatch"):
            validate_candidate(candidate)

    def test_candidate_rejects_unknown_top_level_fields(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["oracle_result"] = True
        with self.assertRaisesRegex(CandidateError, "candidate_fields_invalid"):
            validate_candidate(candidate)

    def test_candidate_rejects_malformed_nested_input_without_type_error(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["ir"]["operations"][-1]["input"][0]["source"] = []
        # Recompute the hash so validation reaches the nested input contract.
        proposal = {
            "service_id": candidate["service_id"],
            "base_revision": candidate["base_revision"],
            "ir": candidate["ir"],
        }
        candidate["change_set_id"] = canonical_digest(proposal)
        with self.assertRaisesRegex(CandidateError, "candidate_input_value_invalid"):
            validate_candidate(candidate)

    def test_trace_parser_accepts_only_successful_proposal_hashes(self):
        digest = self.candidate["change_set_id"]
        events = [
            {
                "event_type": "tool_call",
                "tool_name": "service.propose",
                "change_set_id": digest,
            },
            {
                "event_type": "tool_call",
                "tool_name": "service.propose",
                "failure_class": "ARGUMENT_FIELDS",
            },
            {
                "event_type": "tool_call",
                "tool_name": "service.inspect",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            self.assertEqual(load_trace_proposal_ids(path), {digest})

    def test_candidate_rejects_non_identifier_operation_names(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["ir"]["operations"][-1]["name"] = "invalid-operation-name"
        proposal = {
            "service_id": candidate["service_id"],
            "base_revision": candidate["base_revision"],
            "ir": candidate["ir"],
        }
        candidate["change_set_id"] = canonical_digest(proposal)
        with self.assertRaisesRegex(CandidateError, "candidate_operation_name_invalid"):
            validate_candidate(candidate)

    def test_candidate_rejects_non_identifier_input_names(self):
        candidate = copy.deepcopy(self.candidate)
        candidate["ir"]["operations"][-1]["input"][0]["name"] = "bad name"
        proposal = {
            "service_id": candidate["service_id"],
            "base_revision": candidate["base_revision"],
            "ir": candidate["ir"],
        }
        candidate["change_set_id"] = canonical_digest(proposal)
        with self.assertRaisesRegex(CandidateError, "candidate_input_name_invalid"):
            validate_candidate(candidate)


    def test_candidate_loader_returns_raw_artifact_hash(self):
        encoded = json.dumps(self.candidate, ensure_ascii=False).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_bytes(encoded)
            summary, artifact_sha = load_candidate(
                path,
                traced_change_set_ids={self.candidate["change_set_id"]},
            )
        self.assertEqual(summary["change_set_id"], self.candidate["change_set_id"])
        self.assertEqual(artifact_sha, __import__("hashlib").sha256(encoded).hexdigest())

    def test_candidate_loader_rejects_duplicate_json_keys(self):
        raw = (
            b'{"schema_version":1,"schema_version":1,"task_id":'
            b'"pilot-catalog-add-readonly-operation"}'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_bytes(raw)
            with self.assertRaisesRegex(CandidateError, "duplicate_json_key"):
                load_candidate(path)


if __name__ == "__main__":
    unittest.main()
