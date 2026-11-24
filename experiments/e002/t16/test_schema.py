from __future__ import annotations

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

try:
    import psycopg
except ImportError:
    psycopg = None


@unittest.skipUnless(
    psycopg is not None and os.environ.get("T16_POSTGRES_DSN"),
    "requires the T16 PostgreSQL service",
)
class T16PostgresSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ["T16_POSTGRES_DSN"]

    def setUp(self):
        with psycopg.connect(self.dsn) as db:
            db.execute("SELECT t16_reset()")

    def call(self, *, operation, request_id, body=None, key=None, tenant="tenant-a",
             principal="benchmark-reader", resource_id="fixture-0001", reason=None):
        value = {
            "request_id": request_id,
            "principal_id": principal,
            "tenant_id": tenant,
            "operation": operation,
            "resource_id": resource_id,
            "body": body or {},
        }
        if key is not None:
            value["idempotency_key"] = key
        if reason is not None:
            value["reason_code"] = reason
        with psycopg.connect(self.dsn) as db:
            return db.execute("SELECT t16_handle(%s::jsonb)", (json.dumps(value),)).fetchone()[0]

    def counts(self):
        with psycopg.connect(self.dsn) as db:
            return db.execute("""
                SELECT
                  (SELECT count(*) FROM t16_jobs),
                  (SELECT count(*) FROM t16_outbox),
                  (SELECT count(*) FROM t16_idempotency_records),
                  (SELECT count(*) FROM t16_audit),
                  (SELECT count(*) FROM t16_integrity_violations)
            """).fetchone()

    def test_read_validate_and_expected_denial_are_durably_audited(self):
        read = self.call(operation="authorized_read", request_id="read-1")
        plan = self.call(
            operation="validate_plan", request_id="plan-1",
            body={"contract_version": "v1", "operation": "catalog.read", "resource_id": "fixture-0001"},
        )
        denied = self.call(
            operation="expected_denial", request_id="deny-1", principal="benchmark-limited", reason="MISSING_CAPABILITY",
        )
        self.assertEqual(read["data"]["id"], "fixture-0001")
        self.assertEqual(plan["decision"], "allow")
        self.assertEqual(denied["error"]["code"], "CAPABILITY_DENIED")
        with psycopg.connect(self.dsn) as db:
            audit_reason = db.execute(
                "SELECT reason_code FROM t16_audit WHERE request_id='deny-1'"
            ).fetchone()[0]
        self.assertEqual(audit_reason, "MISSING_CAPABILITY")
        self.assertEqual(self.counts(), (0, 0, 0, 3, 0))

    def test_job_outbox_idempotency_and_audit_commit_atomically(self):
        body = {
            "contract_version": "v1",
            "operation": "jobs.create",
            "payload": {"fixture": "lamp", "amount": 2},
        }
        created = self.call(
            operation="job_admission", request_id="job-1", body=body, key="idem-1",
        )
        replay = self.call(
            operation="job_admission", request_id="job-2", body=body, key="idem-1",
        )
        conflict = self.call(
            operation="job_admission", request_id="job-3",
            body={**body, "payload": {"fixture": "desk"}}, key="idem-1",
        )
        self.assertEqual(created["status"], "queued")
        self.assertEqual(replay["job_id"], created["job_id"])
        self.assertEqual(replay["request_id"], "job-2")
        self.assertEqual(conflict["error"]["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.counts(), (1, 1, 1, 3, 0))

    def test_concurrent_same_key_has_one_durable_job(self):
        body = {
            "contract_version": "v1",
            "operation": "jobs.create",
            "payload": {"fixture": "same"},
        }

        def submit(index):
            return self.call(
                operation="job_admission", request_id=f"race-{index}",
                body=body, key="race-key",
            )

        with ThreadPoolExecutor(max_workers=32) as pool:
            outcomes = list(pool.map(submit, range(32)))
        self.assertEqual(len({item["job_id"] for item in outcomes}), 1)
        self.assertEqual(self.counts(), (1, 1, 1, 32, 0))


    def test_unknown_top_level_contract_fields_fail_closed(self):
        validate = self.call(
            operation="validate_plan", request_id="plan-extra",
            body={
                "contract_version": "v1", "operation": "catalog.read",
                "resource_id": "fixture-0001", "unexpected": True,
            },
        )
        job = self.call(
            operation="job_admission", request_id="job-extra",
            body={
                "contract_version": "v1", "operation": "jobs.create",
                "payload": {"fixture": "safe"}, "unexpected": True,
            },
            key="extra-field-key",
        )
        self.assertEqual(validate["error"]["code"], "INVALID_CONTRACT")
        self.assertEqual(job["error"]["code"], "INVALID_CONTRACT")
        self.assertEqual(self.counts(), (0, 0, 0, 2, 0))

    def test_audit_rows_are_append_only(self):
        self.call(operation="expected_denial", request_id="immutable")
        with psycopg.connect(self.dsn) as db:
            with self.assertRaises(psycopg.Error):
                db.execute("UPDATE t16_audit SET reason_code='tampered'")
                db.commit()
            db.rollback()
            with self.assertRaises(psycopg.Error):
                db.execute("DELETE FROM t16_audit")
                db.commit()


if __name__ == "__main__":
    unittest.main()
