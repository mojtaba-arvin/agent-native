from __future__ import annotations

import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

if psycopg is not None:
    from postgres_reference_adapter import PostgresReferenceAdapter
else:
    PostgresReferenceAdapter = None


@unittest.skipUnless(
    os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN") and psycopg is not None,
    "requires the E-002 PostgreSQL service and psycopg",
)
class PostgresReferenceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ["AGENT_NATIVE_E002_POSTGRES_DSN"]
        self.adapter = PostgresReferenceAdapter(self.dsn)
        self.adapter.reset()

    def audit(self, request_id, operation="jobs.create"):
        return {"request_id": request_id, "operation_id": operation, "created_at": 100}

    def admit(self, *, tenant="tenant-a", operation="jobs.create", key="key-1",
              payload=None, request_id="attempt-1", adapter=None):
        return (adapter or self.adapter).admit_job(
            tenant_id=tenant, operation_id=operation, idempotency_key=key,
            payload={"name": "lamp"} if payload is None else payload,
            outbox_payload={"topic": "job.created"},
            audit_event=self.audit(request_id, operation),
        )

    def test_atomic_admission_and_engine_durability_metadata(self):
        status, outcome = self.admit()
        self.assertEqual(status, "created")
        self.assertEqual(self.adapter.read_job(outcome["job_id"])["state"], "queued")
        self.assertIsNotNone(self.adapter.read_outbox_for_job(outcome["job_id"]))
        self.assertEqual(self.adapter.lookup_idempotency("tenant-a", "jobs.create", "key-1")["outcome"], outcome)
        self.assertEqual(self.adapter.recover(), {
            "e002_jobs": 1, "e002_outbox": 1,
            "e002_idempotency_records": 1, "e002_audit": 1,
        })
        metadata = self.adapter.metadata()
        self.assertEqual(metadata["engine"], "postgresql")
        self.assertTrue(metadata["engine_version"])
        self.assertEqual(metadata["fsync"], "on")
        self.assertEqual(metadata["synchronous_commit"], "on")
        self.assertEqual(metadata["canonicalization_version"], "json-sort-keys-compact-utf8-v1")

    def test_failure_after_each_precommit_write_rolls_back_all_records(self):
        for stage in ("after_job", "after_outbox", "after_idempotency", "after_audit"):
            with self.subTest(stage=stage):
                self.adapter.reset()

                def fail(current):
                    if current == stage:
                        raise OSError("injected pre-commit failure")

                faulty = PostgresReferenceAdapter(self.dsn, _fault_hook=fail)
                with self.assertRaisesRegex(OSError, "injected"):
                    self.admit(adapter=faulty, request_id=f"fault-{stage}")
                self.assertEqual(self.adapter.recover(), {
                    "e002_jobs": 0, "e002_outbox": 0,
                    "e002_idempotency_records": 0, "e002_audit": 0,
                })

    def test_commit_then_process_crash_before_response_reconciles(self):
        child = """
import os, sys
from postgres_reference_adapter import PostgresReferenceAdapter

def terminate_after_commit(stage):
    if stage == "after_commit":
        os._exit(77)

adapter = PostgresReferenceAdapter(sys.argv[1], _fault_hook=terminate_after_commit)
adapter.admit_job(
    tenant_id="tenant-a", operation_id="jobs.create", idempotency_key="key-1",
    payload={"name": "lamp"}, outbox_payload={"topic": "job.created"},
    audit_event={"request_id": "crash-after-commit", "operation_id": "jobs.create", "created_at": 100},
)
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        crashed = subprocess.run(
            [sys.executable, "-c", child, self.dsn],
            env=env, check=False, timeout=20,
        )
        self.assertEqual(crashed.returncode, 77)
        status, outcome = self.admit(request_id="retry-after-process-crash")
        self.assertEqual(status, "replayed")
        self.assertEqual(outcome["state"], "queued")
        self.assertEqual(self.adapter.recover(), {
            "e002_jobs": 1, "e002_outbox": 1,
            "e002_idempotency_records": 1, "e002_audit": 2,
        })

    def test_same_key_replay_conflict_and_tenant_operation_scope(self):
        first = self.admit()
        replay = self.admit(request_id="replay")
        conflict = self.admit(payload={"name": "desk"}, request_id="conflict")
        other_tenant = self.admit(tenant="tenant-b", request_id="tenant-b")
        other_operation = self.admit(operation="jobs.rebuild", request_id="other-op")
        self.assertEqual(first[0], "created")
        self.assertEqual(replay[0], "replayed")
        self.assertEqual(replay[1], first[1])
        self.assertEqual(conflict[0], "conflict")
        self.assertEqual(other_tenant[0], "created")
        self.assertEqual(other_operation[0], "created")
        self.assertEqual(self.adapter.recover()["e002_jobs"], 3)

    def test_32_concurrent_same_hash_submissions_have_one_winner(self):
        def submit(index):
            return self.admit(request_id=f"same-{index}")

        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(submit, range(32)))
        self.assertEqual(sum(status == "created" for status, _ in results), 1)
        self.assertEqual(sum(status == "replayed" for status, _ in results), 31)
        self.assertEqual(len({outcome["job_id"] for _, outcome in results}), 1)
        self.assertEqual(self.adapter.recover()["e002_jobs"], 1)
        self.assertEqual(self.adapter.recover()["e002_audit"], 32)

    def test_32_concurrent_different_hashes_have_one_winner(self):
        def submit(index):
            return self.admit(payload={"name": f"lamp-{index}"}, request_id=f"diff-{index}")

        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(submit, range(32)))
        self.assertEqual(sum(status == "created" for status, _ in results), 1)
        self.assertEqual(sum(status == "conflict" for status, _ in results), 31)
        self.assertEqual(self.adapter.recover()["e002_jobs"], 1)
        self.assertEqual(self.adapter.recover()["e002_audit"], 32)

    def test_audit_storage_outage_fails_closed(self):
        with self.adapter._connect() as db:
            db.execute("""
                CREATE OR REPLACE FUNCTION e002_reject_audit_insert()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'audit_unavailable'; END;
                $$
            """)
            db.execute("""
                CREATE TRIGGER e002_reject_audit_insert BEFORE INSERT ON e002_audit
                FOR EACH ROW EXECUTE FUNCTION e002_reject_audit_insert()
            """)
        try:
            with self.assertRaisesRegex(psycopg.Error, "audit_unavailable"):
                self.admit()
            self.assertEqual(self.adapter.recover(), {
                "e002_jobs": 0, "e002_outbox": 0,
                "e002_idempotency_records": 0, "e002_audit": 0,
            })
        finally:
            with self.adapter._connect() as db:
                db.execute("DROP TRIGGER IF EXISTS e002_reject_audit_insert ON e002_audit")
                db.execute("DROP FUNCTION IF EXISTS e002_reject_audit_insert()")

    def test_audit_is_append_only(self):
        self.admit()
        with self.adapter._connect() as db:
            with self.assertRaisesRegex(psycopg.Error, "audit_append_only"):
                db.execute("UPDATE e002_audit SET reason_code='tampered'")
            db.rollback()
            with self.assertRaisesRegex(psycopg.Error, "audit_append_only"):
                db.execute("DELETE FROM e002_audit")
            db.rollback()
            with self.assertRaisesRegex(psycopg.Error, "audit_append_only"):
                db.execute("TRUNCATE e002_audit")


    def test_outbox_lease_expiry_fences_stale_acknowledgement(self):
        _status, outcome = self.admit()
        first = self.adapter.claim_outbox(consumer="relay-a", limit=1, lease_seconds=5, now=100)
        self.assertEqual(len(first), 1)
        self.assertEqual(self.adapter.claim_outbox(
            consumer="relay-b", limit=1, lease_seconds=5, now=104
        ), [])
        second = self.adapter.claim_outbox(consumer="relay-b", limit=1, lease_seconds=5, now=106)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["lease_token"], first[0]["lease_token"] + 1)
        self.assertFalse(self.adapter.ack_outbox(
            event_id=str(first[0]["event_id"]), consumer="relay-a",
            lease_token=first[0]["lease_token"], now=107,
        ))
        self.assertTrue(self.adapter.ack_outbox(
            event_id=str(second[0]["event_id"]), consumer="relay-b",
            lease_token=second[0]["lease_token"], now=107,
        ))
        self.assertEqual(self.adapter.claim_outbox(
            consumer="relay-c", limit=1, lease_seconds=5, now=108
        ), [])


    def test_t06_http_conformance_on_postgres(self):
        """Run the complete E-009 T04 HTTP suite on this job's PostgreSQL 16.4 service.

        This keeps the T06 database-backed conformance check in the existing
        Layer 1 PostgreSQL job and reuses its pinned psycopg installation.
        """
        repository_root = Path(__file__).resolve().parents[2]
        environment = dict(os.environ)
        python_paths = [
            str(repository_root / "src"),
            str(repository_root / "experiments" / "e009"),
        ]
        if environment.get("PYTHONPATH"):
            python_paths.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)
        command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(repository_root / "experiments" / "e009"),
            "-p",
            "test_postgres_http_conformance.py",
            "-v",
        ]
        completed = subprocess.run(
            command,
            cwd=repository_root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + "\n" + completed.stderr,
        )
        output = completed.stdout + completed.stderr
        self.assertIn("Ran 14 tests", output)
        self.assertIn("OK", output)
        self.assertNotIn("skipped=", output)
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")



if __name__ == "__main__":
    unittest.main()


# T11 production runtime parity is exercised in the same Layer 1 PostgreSQL
# invocation as the storage reference adapter. Importing the test case here
# keeps it out of a separate CI-only path and makes the fast suite skip it
# cleanly when no disposable PostgreSQL DSN is configured.
import sys as _sys
from pathlib import Path as _Path

_root = _Path(__file__).resolve().parents[2]\n_sys.path.insert(0, str(_root / "src"))\n_sys.path.insert(0, str(_root / "tests"))
from test_production_core_postgres import ProductionCorePostgresTests  # noqa: E402,F401
