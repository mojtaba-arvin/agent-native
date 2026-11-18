from __future__ import annotations

import os
import tempfile
import unittest

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
