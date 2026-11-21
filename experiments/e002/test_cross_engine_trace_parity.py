from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

try:
    import psycopg
except ImportError:
    psycopg = None

if psycopg is not None:
    from postgres_reference_adapter import PostgresReferenceAdapter
else:
    PostgresReferenceAdapter = None

from sqlite_reference_adapter import SQLiteReferenceAdapter
from trace_runner import run_reference_trace


@unittest.skipUnless(
    os.environ.get("AGENT_NATIVE_E002_POSTGRES_DSN") and psycopg is not None,
    "requires disposable PostgreSQL service and psycopg",
)
class CrossEngineTraceParityTests(unittest.TestCase):
    def test_process_crash_after_commit_reconciles_identically_on_both_engines(self):
        dsn = os.environ["AGENT_NATIVE_E002_POSTGRES_DSN"]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).parent)
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "crash.sqlite3")
            postgres = PostgresReferenceAdapter(dsn)
            postgres.reset()

            sqlite_child = """
import os, sys
from sqlite_reference_adapter import SQLiteReferenceAdapter
def crash(stage):
    if stage == "after_commit":
        os._exit(77)
adapter = SQLiteReferenceAdapter(sys.argv[1], _fault_hook=crash)
adapter.admit_job(
    tenant_id="tenant-crash", operation_id="jobs.create", idempotency_key="crash-key",
    payload={"resource": "lamp"}, outbox_payload={"topic": "job.created"},
    audit_event={"request_id": "crash-before-response", "operation_id": "jobs.create", "created_at": 100},
)
"""
            postgres_child = """
import os, sys
from postgres_reference_adapter import PostgresReferenceAdapter
def crash(stage):
    if stage == "after_commit":
        os._exit(77)
adapter = PostgresReferenceAdapter(sys.argv[1], _fault_hook=crash)
adapter.admit_job(
    tenant_id="tenant-crash", operation_id="jobs.create", idempotency_key="crash-key",
    payload={"resource": "lamp"}, outbox_payload={"topic": "job.created"},
    audit_event={"request_id": "crash-before-response", "operation_id": "jobs.create", "created_at": 100},
)
"""
            sqlite_crash = subprocess.run(
                [sys.executable, "-c", sqlite_child, sqlite_path],
                env=env, check=False, timeout=20,
            )
            postgres_crash = subprocess.run(
                [sys.executable, "-c", postgres_child, dsn],
                env=env, check=False, timeout=20,
            )
            self.assertEqual(sqlite_crash.returncode, 77)
            self.assertEqual(postgres_crash.returncode, 77)

            sqlite = SQLiteReferenceAdapter(sqlite_path)
            postgres = PostgresReferenceAdapter(dsn)
            replay_results = []
            for adapter in (sqlite, postgres):
                status, outcome = adapter.admit_job(
                    tenant_id="tenant-crash", operation_id="jobs.create",
                    idempotency_key="crash-key", payload={"resource": "lamp"},
                    outbox_payload={"topic": "job.created"},
                    audit_event={
                        "request_id": "retry-after-crash",
                        "operation_id": "jobs.create",
                        "created_at": 101,
                    },
                )
                counts = adapter.recover()
                counts = {key.removeprefix("e002_"): value for key, value in counts.items()}
                replay_results.append({
                    "status": status,
                    "state": outcome["state"],
                    "counts": counts,
                })

        self.assertEqual(replay_results[0], replay_results[1])
        self.assertEqual(replay_results[0]["status"], "replayed")
        self.assertEqual(replay_results[0]["counts"], {
            "jobs": 1, "outbox": 1, "idempotency_records": 1, "audit": 2,
        })

    def test_precommit_faults_have_identical_atomic_rollback_on_both_engines(self):
        dsn = os.environ["AGENT_NATIVE_E002_POSTGRES_DSN"]
        stages = ("after_job", "after_outbox", "after_idempotency", "after_audit")
        with tempfile.TemporaryDirectory() as directory:
            for stage in stages:
                def fail(current):
                    if current == stage:
                        raise OSError(f"injected-{stage}")

                sqlite = SQLiteReferenceAdapter(
                    os.path.join(directory, f"fault-{stage}.sqlite3"),
                    _fault_hook=fail,
                )
                postgres = PostgresReferenceAdapter(dsn, _fault_hook=fail)
                postgres.reset()

                def submit(adapter):
                    adapter.admit_job(
                        tenant_id="tenant-fault",
                        operation_id="jobs.create",
                        idempotency_key=f"fault-{stage}",
                        payload={"stage": stage},
                        outbox_payload={"topic": "fault.test"},
                        audit_event={
                            "request_id": f"fault-{stage}",
                            "operation_id": "jobs.create",
                            "created_at": 1000,
                        },
                    )

                with self.assertRaisesRegex(OSError, f"injected-{stage}"):
                    submit(sqlite)
                with self.assertRaisesRegex(OSError, f"injected-{stage}"):
                    submit(postgres)

                sqlite_counts = sqlite.recover()
                postgres_counts = {
                    key.removeprefix("e002_"): value
                    for key, value in postgres.recover().items()
                }
                self.assertEqual(sqlite_counts, postgres_counts)
                self.assertEqual(sqlite_counts, {
                    "jobs": 0, "outbox": 0, "idempotency_records": 0, "audit": 0,
                })

    def test_identical_generated_traces_have_identical_sqlite_and_postgres_outcomes(self):
        dsn = os.environ["AGENT_NATIVE_E002_POSTGRES_DSN"]
        seeds = tuple(range(20261118, 20261143))
        digests = []
        with tempfile.TemporaryDirectory() as directory:
            postgres = PostgresReferenceAdapter(dsn)
            for seed in seeds:
                sqlite = SQLiteReferenceAdapter(os.path.join(directory, f"trace-{seed}.sqlite3"))
                postgres.reset()
                sqlite_result = run_reference_trace(sqlite, seed=seed)
                postgres_result = run_reference_trace(postgres, seed=seed)
                self.assertEqual(sqlite_result, postgres_result)
                self.assertEqual(sqlite_result["operations"], 60)
                self.assertEqual(
                    sqlite_result["outbox_claimed"], sqlite_result["record_counts"]["jobs"]
                )
                self.assertEqual(sqlite_result["outbox_acked"], sqlite_result["outbox_claimed"])
                self.assertEqual(sqlite_result["stale_ack_rejected"], sqlite_result["outbox_claimed"])
                digests.append(sqlite_result["trace_digest"])

        self.assertEqual(len(set(digests)), len(seeds))
        self.assertEqual(len(seeds) * 60, 1500)


    def test_canonical_request_hashes_match_across_engines(self):
        dsn = os.environ["AGENT_NATIVE_E002_POSTGRES_DSN"]
        with tempfile.TemporaryDirectory() as directory:
            sqlite = SQLiteReferenceAdapter(Path(directory) / "canonical.sqlite3")
            postgres = PostgresReferenceAdapter(dsn)
            postgres.reset()

            # Semantically identical nested JSON with deliberately different
            # insertion order must have the same versioned canonical hash.
            sqlite_payload = {
                "name": "Desk lamp",
                "details": {
                    "manufacturer": "Ångström",
                    "attributes": {"z": 3, "a": 1},
                },
            }
            postgres_payload = {
                "details": {
                    "attributes": {"a": 1, "z": 3},
                    "manufacturer": "Ångström",
                },
                "name": "Desk lamp",
            }

            def submit(adapter, payload, key, request_id):
                return adapter.admit_job(
                    tenant_id="tenant-canonical",
                    operation_id="jobs.create",
                    idempotency_key=key,
                    payload=payload,
                    outbox_payload={"topic": "job.created"},
                    audit_event={
                        "request_id": request_id,
                        "operation_id": "jobs.create",
                        "created_at": 2000,
                    },
                )

            sqlite_status, _ = submit(
                sqlite, sqlite_payload, "canonical-same", "sqlite-canonical-same"
            )
            postgres_status, _ = submit(
                postgres, postgres_payload, "canonical-same", "postgres-canonical-same"
            )
            self.assertEqual(sqlite_status, "created")
            self.assertEqual(postgres_status, "created")

            sqlite_hash = sqlite.lookup_idempotency(
                "tenant-canonical", "jobs.create", "canonical-same"
            )["request_hash"]
            postgres_hash = postgres.lookup_idempotency(
                "tenant-canonical", "jobs.create", "canonical-same"
            )["request_hash"]
            self.assertRegex(sqlite_hash, r"^[0-9a-f]{64}$")
            self.assertEqual(sqlite_hash, postgres_hash)
            self.assertEqual(
                sqlite.metadata()["canonicalization_version"],
                postgres.metadata()["canonicalization_version"],
            )

            changed_sqlite_payload = {
                "name": "Desk lamp",
                "details": {
                    "manufacturer": "Ångström",
                    "attributes": {"z": 4, "a": 1},
                },
            }
            changed_postgres_payload = {
                "details": {
                    "attributes": {"a": 1, "z": 4},
                    "manufacturer": "Ångström",
                },
                "name": "Desk lamp",
            }
            self.assertEqual(
                submit(
                    sqlite,
                    changed_sqlite_payload,
                    "canonical-changed",
                    "sqlite-canonical-changed",
                )[0],
                "created",
            )
            self.assertEqual(
                submit(
                    postgres,
                    changed_postgres_payload,
                    "canonical-changed",
                    "postgres-canonical-changed",
                )[0],
                "created",
            )
            changed_sqlite_hash = sqlite.lookup_idempotency(
                "tenant-canonical", "jobs.create", "canonical-changed"
            )["request_hash"]
            changed_postgres_hash = postgres.lookup_idempotency(
                "tenant-canonical", "jobs.create", "canonical-changed"
            )["request_hash"]
            self.assertEqual(changed_sqlite_hash, changed_postgres_hash)
            self.assertNotEqual(changed_sqlite_hash, sqlite_hash)

    def test_append_audit_sequence_is_monotonic_after_reopen_on_both_engines(self):
        dsn = os.environ["AGENT_NATIVE_E002_POSTGRES_DSN"]
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = Path(directory) / "audit-sequence.sqlite3"
            sqlite = SQLiteReferenceAdapter(sqlite_path)
            postgres = PostgresReferenceAdapter(dsn)
            postgres.reset()

            def event(request_id):
                return {
                    "event_id": str(uuid.uuid4()),
                    "request_id": request_id,
                    "tenant_id": "tenant-a",
                    "operation_id": "jobs.create",
                    "decision": "allow",
                    "reason_code": "T05_AUDIT_SEQUENCE",
                    "outcome": {"source": "cross-engine-conformance"},
                    "created_at": 3000,
                }

            sqlite_first = sqlite.append_audit(event("sqlite-audit-1"))
            postgres_first = postgres.append_audit(event("postgres-audit-1"))

            sqlite_reopened = SQLiteReferenceAdapter(sqlite_path)
            postgres_reopened = PostgresReferenceAdapter(dsn)
            sqlite_second = sqlite_reopened.append_audit(event("sqlite-audit-2"))
            postgres_second = postgres_reopened.append_audit(event("postgres-audit-2"))

            self.assertGreater(sqlite_second, sqlite_first)
            self.assertGreater(postgres_second, postgres_first)
            self.assertEqual(
                [sqlite_first, sqlite_second],
                [postgres_first, postgres_second],
            )
            self.assertEqual(sqlite_reopened.recover()["audit"], 2)
            self.assertEqual(
                postgres_reopened.recover()["e002_audit"],
                2,
            )



if __name__ == "__main__":
    unittest.main()
