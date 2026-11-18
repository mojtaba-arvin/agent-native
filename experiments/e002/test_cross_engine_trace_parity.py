from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
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
        seeds = (20261118, 20261119, 20261120, 20261121, 20261122)
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
                digests.append(sqlite_result["trace_digest"])

        self.assertEqual(len(set(digests)), len(seeds))


if __name__ == "__main__":
    unittest.main()
