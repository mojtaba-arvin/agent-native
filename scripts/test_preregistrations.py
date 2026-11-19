import json
import tempfile
import unittest
from pathlib import Path

from check_preregistrations import event_hash, git_blob_sha1, validate


BASELINE_ID = "DECISION-BASELINE-TEST"
RECORD_ID = "COHORT-TEST"


class PreregistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "project-control").mkdir()
        (self.root / "research").mkdir()
        (self.root / "project-control" / "RUN_LEDGER.jsonl").write_text('{"event_id": "RUN-1"}\n', encoding="utf-8")
        (self.root / "DECISIONS.json").write_text('{"decisions": []}\n', encoding="utf-8")
        (self.root / "research" / "design-decisions.md").write_text("# Decisions\n", encoding="utf-8")
        (self.root / "manifest.json").write_text('{"no_apply": true}\n', encoding="utf-8")
        self.registry = {
            "schema_version": 1,
            "baseline_event_id": BASELINE_ID,
            "records": [{
                "record_id": RECORD_ID,
                "kind": "cohort_manifest",
                "path": "manifest.json",
                "git_blob_sha1": git_blob_sha1(self.root / "manifest.json"),
                "status": "ready_for_manual_dispatch",
                "run_ids": [],
                "decision_event_id": BASELINE_ID,
                "no_apply": True,
            }],
        }
        self.event = {
            "event_id": BASELINE_ID,
            "timestamp": "2026-11-19T00:00:00Z",
            "previous_event_hash": None,
            "previous_decision_file_blob_sha1": None,
            "previous_decision_log_blob_sha1": None,
            "previous_preregistrations_blob_sha1": None,
            "decision_file_blob_sha1": git_blob_sha1(self.root / "DECISIONS.json"),
            "decision_log_blob_sha1": git_blob_sha1(self.root / "research" / "design-decisions.md"),
            "preregistrations_blob_sha1": None,
            "rationale": "Pin baseline fixture without changing decision values.",
            "affected_decision_ids": [],
            "affected_preregistration_ids": [RECORD_ID],
            "evidence_ids": ["fixture"],
        }
        self.refresh_baseline()

    def tearDown(self):
        self.temp.cleanup()

    @property
    def registry_path(self):
        return self.root / "project-control" / "PREREGISTRATIONS.json"

    @property
    def events_path(self):
        return self.root / "project-control" / "DECISION_EVENTS.jsonl"

    def refresh_baseline(self):
        self.registry_path.write_text(json.dumps(self.registry, indent=2) + "\n", encoding="utf-8")
        self.event["preregistrations_blob_sha1"] = git_blob_sha1(self.registry_path)
        self.event["event_hash"] = event_hash(self.event)
        self.events_path.write_text(json.dumps(self.event) + "\n", encoding="utf-8")

    def append_run_ledger_pin(self):
        second = dict(self.event)
        second.update({
            "event_id": "DECISION-RUN-LEDGER-PIN",
            "timestamp": "2026-11-19T01:00:00Z",
            "previous_event_hash": self.event["event_hash"],
            "previous_decision_file_blob_sha1": self.event["decision_file_blob_sha1"],
            "previous_decision_log_blob_sha1": self.event["decision_log_blob_sha1"],
            "previous_preregistrations_blob_sha1": self.event["preregistrations_blob_sha1"],
            "previous_run_ledger_blob_sha1": None,
            "run_ledger_blob_sha1": git_blob_sha1(self.root / "project-control" / "RUN_LEDGER.jsonl"),
            "rationale": "Pin the append-only run ledger baseline.",
            "evidence_ids": ["RUN_LEDGER.jsonl"],
        })
        second["event_hash"] = event_hash(second)
        self.events_path.write_text(
            json.dumps(self.event) + "\n" + json.dumps(second) + "\n",
            encoding="utf-8",
        )
        return second

    def test_accepts_frozen_manifest_and_baseline_chain(self):
        self.assertEqual(validate(self.root), [])

    def test_rejects_modified_frozen_manifest(self):
        (self.root / "manifest.json").write_text('{"no_apply": false}\n', encoding="utf-8")
        self.assertTrue(any("manifest hash changed" in error for error in validate(self.root)))

    def test_rejects_modified_decision_register_without_event(self):
        (self.root / "DECISIONS.json").write_text('{"decisions": ["changed"]}\n', encoding="utf-8")
        self.assertTrue(any("not pinned by the latest decision event" in error for error in validate(self.root)))

    def test_rejects_modified_registry_without_event(self):
        with self.registry_path.open("a", encoding="utf-8") as handle:
            handle.write(" ")
        self.assertTrue(any("PREREGISTRATIONS.json" in error and "not pinned" in error for error in validate(self.root)))

    def test_rejects_duplicate_record_ids(self):
        self.registry["records"].append(dict(self.registry["records"][0]))
        self.refresh_baseline()
        self.assertTrue(any("duplicate record_id" in error for error in validate(self.root)))

    def test_rejects_path_traversal(self):
        self.registry["records"][0]["path"] = "../outside.json"
        self.refresh_baseline()
        self.assertTrue(any("path escapes repository root" in error for error in validate(self.root)))

    def test_rejects_ready_manifest_without_no_apply(self):
        self.registry["records"][0]["no_apply"] = False
        self.refresh_baseline()
        self.assertTrue(any("requires no_apply=true" in error for error in validate(self.root)))

    def test_rejects_dispatched_record_without_run_id(self):
        self.registry["records"][0]["status"] = "dispatched"
        self.refresh_baseline()
        self.assertTrue(any("requires at least one run ID" in error for error in validate(self.root)))

    def test_rejects_boolean_run_id(self):
        self.registry["records"][0]["status"] = "dispatched"
        self.registry["records"][0]["run_ids"] = [True]
        self.refresh_baseline()
        self.assertTrue(any("positive integer IDs" in error for error in validate(self.root)))

    def test_rejects_duplicate_run_ids(self):
        self.registry["records"][0]["status"] = "dispatched"
        self.registry["records"][0]["run_ids"] = [123, 123]
        self.refresh_baseline()
        self.assertTrue(any("run_ids must not contain duplicates" in error for error in validate(self.root)))

    def test_rejects_unknown_decision_event_reference(self):
        self.registry["records"][0]["decision_event_id"] = "MISSING"
        self.refresh_baseline()
        self.assertTrue(any("decision_event_id does not resolve" in error for error in validate(self.root)))

    def test_draft_manifest_can_change_before_freeze(self):
        self.registry["records"][0]["status"] = "draft"
        self.refresh_baseline()
        (self.root / "manifest.json").write_text('{"draft_revision": 2}\n', encoding="utf-8")
        self.assertEqual(validate(self.root), [])

    def test_rejects_event_hash_tampering(self):
        self.event["rationale"] = "tampered without recalculating the event hash"
        self.events_path.write_text(json.dumps(self.event) + "\n", encoding="utf-8")
        self.assertTrue(any("event_hash does not match" in error for error in validate(self.root)))

    def test_rejects_broken_previous_event_hash(self):
        second = dict(self.event)
        second.update({
            "event_id": "DECISION-SECOND",
            "timestamp": "2026-11-19T01:00:00Z",
            "previous_event_hash": "0" * 64,
            "previous_decision_file_blob_sha1": self.event["decision_file_blob_sha1"],
            "previous_decision_log_blob_sha1": self.event["decision_log_blob_sha1"],
            "previous_preregistrations_blob_sha1": self.event["preregistrations_blob_sha1"],
            "rationale": "A second event with a deliberately broken chain.",
        })
        second["event_hash"] = event_hash(second)
        self.events_path.write_text(
            json.dumps(self.event) + "\n" + json.dumps(second) + "\n",
            encoding="utf-8",
        )
        self.assertTrue(any("broken previous_event_hash chain" in error for error in validate(self.root)))

    def test_accepts_run_ledger_pin_chain(self):
        self.append_run_ledger_pin()
        self.assertEqual(validate(self.root), [])

    def test_rejects_modified_run_ledger_after_pin(self):
        self.append_run_ledger_pin()
        with (self.root / "project-control" / "RUN_LEDGER.jsonl").open("a", encoding="utf-8") as handle:
            handle.write('{"event_id": "RUN-2"}\n')
        self.assertTrue(any("RUN_LEDGER.jsonl" in error and "not pinned" in error for error in validate(self.root)))

    def test_rejects_broken_run_ledger_previous_hash(self):
        second = self.append_run_ledger_pin()
        third = dict(second)
        third.update({
            "event_id": "DECISION-RUN-LEDGER-PIN-2",
            "timestamp": "2026-11-19T02:00:00Z",
            "previous_event_hash": second["event_hash"],
            "previous_run_ledger_blob_sha1": "0" * 40,
            "rationale": "Deliberately broken run-ledger chain.",
        })
        third["event_hash"] = event_hash(third)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(third) + "\n")
        self.assertTrue(any("previous_run_ledger_blob_sha1 does not match" in error for error in validate(self.root)))

    def test_rejects_unknown_decision_reference(self):
        self.event["affected_decision_ids"] = ["D-MISSING"]
        self.event["event_hash"] = event_hash(self.event)
        self.events_path.write_text(json.dumps(self.event) + "\n", encoding="utf-8")
        self.assertTrue(any("unknown decision IDs D-MISSING" in error for error in validate(self.root)))

    def test_rejects_duplicate_decision_ids(self):
        (self.root / "DECISIONS.json").write_text(
            json.dumps({"decisions": [{"id": "D-1"}, {"id": "D-1"}]}) + "\n",
            encoding="utf-8",
        )
        self.assertTrue(any("duplicate decision id D-1" in error for error in validate(self.root)))

    def test_rejects_cohort_manifest_without_no_apply_flag(self):
        (self.root / "manifest.json").write_text('{"no_apply": false}\n', encoding="utf-8")
        self.registry["records"][0]["git_blob_sha1"] = git_blob_sha1(self.root / "manifest.json")
        self.refresh_baseline()
        self.assertTrue(any("referenced cohort manifest must declare no_apply=true" in error for error in validate(self.root)))

    def test_rejects_draft_cohort_metadata_without_no_apply(self):
        self.registry["records"][0]["status"] = "draft"
        self.registry["records"][0]["no_apply"] = False
        self.refresh_baseline()
        self.assertTrue(any("agent cohort manifests must remain no-apply" in error for error in validate(self.root)))

    def test_rejects_invalid_status_type_without_crashing(self):
        self.registry["records"][0]["status"] = {"unexpected": "object"}
        self.refresh_baseline()
        self.assertTrue(any("unsupported status" in error for error in validate(self.root)))

    def test_rejects_timezone_naive_event_timestamp(self):
        self.event["timestamp"] = "2026-11-19T00:00:00"
        self.event["event_hash"] = event_hash(self.event)
        self.events_path.write_text(json.dumps(self.event) + "\n", encoding="utf-8")
        self.assertTrue(any("explicit timezone" in error for error in validate(self.root)))

    def test_rejects_invalid_event_timestamp(self):
        self.event["timestamp"] = "not-a-date"
        self.event["event_hash"] = event_hash(self.event)
        self.events_path.write_text(json.dumps(self.event) + "\n", encoding="utf-8")
        self.assertTrue(any("invalid ISO-8601 timestamp" in error for error in validate(self.root)))


if __name__ == "__main__":
    unittest.main()
