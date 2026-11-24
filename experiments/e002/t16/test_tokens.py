from __future__ import annotations

import unittest

from tokens import authorize, issue_benchmark_tokens, issue_token, verify_token


class T16CapabilityTokenTests(unittest.TestCase):
    def setUp(self):
        self.key = "ab" * 32
        self.now = 1_800_000_000

    def test_benchmark_tokens_are_signed_tenant_scoped_and_least_privilege(self):
        reader, limited = issue_benchmark_tokens(self.key, now=self.now)
        reader_claims = verify_token(reader, self.key, now=self.now + 1)
        limited_claims = verify_token(limited, self.key, now=self.now + 1)
        self.assertEqual(reader_claims["principal_id"], "benchmark-reader")
        self.assertEqual(reader_claims["tenant_id"], "tenant-a")
        self.assertEqual(authorize(reader_claims, "catalog.read", "/v1/records/fixture-0001", now=self.now + 1), (True, "ALLOW"))
        self.assertEqual(authorize(reader_claims, "jobs.create", "/v1/jobs", now=self.now + 1), (True, "ALLOW"))
        self.assertEqual(authorize(reader_claims, "catalog.read", "/v1/records/fixture-0002", now=self.now + 1), (False, "RESOURCE_SCOPE"))
        self.assertEqual(authorize(limited_claims, "jobs.create", "/v1/jobs", now=self.now + 1), (False, "MISSING_CAPABILITY"))

    def test_tampering_wrong_key_and_expiry_are_rejected(self):
        token, _ = issue_benchmark_tokens(self.key, now=self.now)
        altered = token[:-1] + ("0" if token[-1] != "0" else "1")
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_token(altered, self.key, now=self.now + 1)
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_token(token, "cd" * 32, now=self.now + 1)
        with self.assertRaisesRegex(ValueError, "validity"):
            verify_token(token, self.key, now=self.now + 601)

    def test_grant_expiry_and_resource_scope_fail_closed(self):
        token = issue_token(
            self.key, "principal-1", "tenant-a",
            (("catalog.read", "/v1/records/one", self.now + 5, 0),),
            ttl_seconds=60, now=self.now,
        )
        claims = verify_token(token, self.key, now=self.now + 1)
        self.assertEqual(authorize(claims, "catalog.read", "/v1/records/one/child", now=self.now + 1), (True, "ALLOW"))
        self.assertEqual(authorize(claims, "catalog.read", "/v1/records/two", now=self.now + 1), (False, "RESOURCE_SCOPE"))
        self.assertEqual(authorize(claims, "catalog.read", "/v1/records/one", now=self.now + 5), (False, "EXPIRED_GRANT"))

    def test_key_and_token_lifetime_limits_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "32_bytes"):
            issue_token("aa" * 16, "principal", "tenant", (("catalog.read", "/v1/records", None, 0),), now=self.now)
        with self.assertRaisesRegex(ValueError, "ttl"):
            issue_token(self.key, "principal", "tenant", (("catalog.read", "/v1/records", None, 0),), ttl_seconds=901, now=self.now)


if __name__ == "__main__":
    unittest.main()
