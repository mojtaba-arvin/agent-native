from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlite_reference_adapter import SQLiteReferenceAdapter


class SQLiteReferenceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "reference.sqlite3"
        self.adapter = SQLiteReferenceAdapter(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def audit(self, request_id, operation="jobs.create"):
        return {
            "request_id": request_id,
            "operation_id": operation,
            "created_at": 100,
        }

    def admit(self, *, tenant="tenant-a", operation="jobs.create", key="key-1",
              payload=None, request_id="attempt-1", adapter=None):
        return (adapter or self.adapter).admit_job(
            tenant_id=tenant,
            operation_id=operation,
            idempotency_key=key,
            payload={"name": "lamp"} if payload is None else payload,
            outbox_payload={"topic": "job.created"},
            audit_event=self.audit(request_id, operation),
        )

    def test_admission_commits_job_outbox_idempotency_and_audit_together(self):
        status, outcome = self.admit()
        self.assertEqual(status, "created")
        self.assertEqual(self.adapter.read_job(outcome["job_id"])["state"], "queued")
        self.assertIsNotNone(self.adapter.read_outbox_for_job(outcome["job_id"]))
        self.assertEqual(self.adapter.lookup_idempotency("tenant-a", "jobs.create", "key-1")["outcome"], outcome)
        self.assertEqual(self.adapter.recover(), {
            "jobs": 1, "outbox": 1, "idempotency_records": 1, "audit": 1,
        })

    def test_failure_after_each_write_rolls_back_all_four_records(self):
        for stage in ("after_job", "after_outbox", "after_idempotency", "after_audit"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / "fault.sqlite3"

                def fail(current):
                    if current == stage:
                        raise OSError("injected pre-commit failure")

                adapter = SQLiteReferenceAdapter(db, _fault_hook=fail)
                with self.assertRaisesRegex(OSError, "injected"):
                    self.admit(adapter=adapter, key="fault-key", request_id=f"fault-{stage}")
                recovered = SQLiteReferenceAdapter(db)
                self.assertEqual(recovered.recover(), {
                    "jobs": 0, "outbox": 0, "idempotency_records": 0, "audit": 0,
                })

    def test_process_crash_after_commit_before_response_reconciles_original_outcome(self):
        child = """
import os, sys
from sqlite_reference_adapter import SQLiteReferenceAdapter

def terminate_after_commit(stage):
    if stage == "after_commit":
        os._exit(77)

adapter = SQLiteReferenceAdapter(sys.argv[1], _fault_hook=terminate_after_commit)
adapter.admit_job(
    tenant_id="tenant-a", operation_id="jobs.create", idempotency_key="key-1",
    payload={"name": "lamp"}, outbox_payload={"topic": "job.created"},
    audit_event={"request_id": "crash-after-commit", "operation_id": "jobs.create", "created_at": 100},
)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        crashed = subprocess.run(
            [sys.executable, "-c", child, str(self.database)],
            env=env, check=False, timeout=10,
        )
        self.assertEqual(crashed.returncode, 77)
        reopened = SQLiteReferenceAdapter(self.database)
        status, outcome = self.admit(adapter=reopened, request_id="retry-after-process-crash")
        self.assertEqual(status, "replayed")
        self.assertEqual(reopened.recover(), {
            "jobs": 1, "outbox": 1, "idempotency_records": 1, "audit": 2,
        })
        self.assertEqual(outcome["state"], "queued")

    def test_outbox_lease_expiry_and_fencing_reject_stale_ack(self):
        _, outcome = self.admit()
        first = self.adapter.claim_outbox(
            consumer="relay-a", limit=1, lease_seconds=5, now=100
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(self.adapter.claim_outbox(
            consumer="relay-b", limit=1, lease_seconds=5, now=104
        ), [])
        second = self.adapter.claim_outbox(
            consumer="relay-b", limit=1, lease_seconds=5, now=106
        )
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["lease_token"], first[0]["lease_token"] + 1)
        self.assertFalse(self.adapter.ack_outbox(
            event_id=first[0]["event_id"], consumer="relay-a",
            lease_token=first[0]["lease_token"], now=107,
        ))
        self.assertTrue(self.adapter.ack_outbox(
            event_id=second[0]["event_id"], consumer="relay-b",
            lease_token=second[0]["lease_token"], now=107,
        ))
        self.assertEqual(self.adapter.claim_outbox(
            consumer="relay-c", limit=1, lease_seconds=5, now=108
        ), [])

    def test_same_key_same_hash_replays_and_different_hash_conflicts(self):
        first_status, first = self.admit()
        replay_status, replay = self.admit(request_id="attempt-2")
        conflict_status, conflict = self.admit(payload={"name": "desk"}, request_id="attempt-3")
        self.assertEqual(first_status, "created")
        self.assertEqual(replay_status, "replayed")
        self.assertEqual(replay, first)
        self.assertEqual(conflict_status, "conflict")
        self.assertEqual(conflict["code"], "IDEMPOTENCY_PAYLOAD_CONFLICT")
        self.assertEqual(self.adapter.recover(), {
            "jobs": 1, "outbox": 1, "idempotency_records": 1, "audit": 3,
        })

    def test_tenant_and_operation_are_both_part_of_idempotency_scope(self):
        first = self.admit()
        other_tenant = self.admit(tenant="tenant-b", request_id="tenant-b")
        other_operation = self.admit(operation="jobs.rebuild", request_id="other-op")
        self.assertEqual(first[0], "created")
        self.assertEqual(other_tenant[0], "created")
        self.assertEqual(other_operation[0], "created")
        self.assertEqual(self.adapter.recover()["jobs"], 3)

    def test_32_concurrent_same_key_submissions_have_one_logical_winner(self):
        def submit(index):
            return self.admit(request_id=f"concurrent-{index}")

        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(submit, range(32)))
        self.assertEqual(sum(status == "created" for status, _ in results), 1)
        self.assertEqual(sum(status == "replayed" for status, _ in results), 31)
        self.assertEqual(len({outcome["job_id"] for _, outcome in results}), 1)
        self.assertEqual(self.adapter.recover(), {
            "jobs": 1, "outbox": 1, "idempotency_records": 1, "audit": 32,
        })

    def test_audit_storage_failure_fails_closed_without_job_or_outbox(self):
        db = sqlite3.connect(self.database)
        try:
            db.execute("""
                CREATE TRIGGER reject_audit_insert BEFORE INSERT ON audit
                BEGIN SELECT RAISE(ABORT, 'audit_unavailable'); END
            """)
            db.commit()
        finally:
            db.close()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "audit_unavailable"):
            self.admit()
        self.assertEqual(self.adapter.recover(), {
            "jobs": 0, "outbox": 0, "idempotency_records": 0, "audit": 0,
        })

    def test_32_concurrent_same_key_different_hashes_have_one_winner(self):
        def submit(index):
            return self.admit(
                payload={"name": f"lamp-{index}"},
                request_id=f"different-hash-{index}",
            )

        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(submit, range(32)))
        self.assertEqual(sum(status == "created" for status, _ in results), 1)
        self.assertEqual(sum(status == "conflict" for status, _ in results), 31)
        self.assertEqual(self.adapter.recover(), {
            "jobs": 1, "outbox": 1, "idempotency_records": 1, "audit": 32,
        })

    def test_audit_is_append_only(self):
        self.admit()
        db = sqlite3.connect(self.database)
        try:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "audit_append_only"):
                db.execute("UPDATE audit SET reason_code='tampered'")
            db.rollback()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "audit_append_only"):
                db.execute("DELETE FROM audit")
            db.rollback()
        finally:
            db.close()

    def test_metadata_reports_pinned_engine_and_durability_profile(self):
        metadata = self.adapter.metadata()
        self.assertEqual(metadata["engine"], "sqlite")
        self.assertTrue(metadata["engine_version"])
        self.assertEqual(metadata["journal_mode"].lower(), "wal")
        self.assertEqual(metadata["synchronous"], 2)
        self.assertEqual(metadata["foreign_keys"], 1)
        self.assertEqual(metadata["busy_timeout_ms"], 10000)
        self.assertEqual(metadata["canonicalization_version"], "json-sort-keys-compact-utf8-v1")

    def test_memory_database_is_rejected_for_durable_contract(self):
        with self.assertRaisesRegex(ValueError, "file_backed"):
            SQLiteReferenceAdapter(":memory:")


if __name__ == "__main__":
    unittest.main()
