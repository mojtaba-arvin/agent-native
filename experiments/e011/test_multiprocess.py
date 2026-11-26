from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.client import RemoteDisconnected
from urllib.error import URLError

from multiprocess import effect_count, invoke, start_receiver


class MultiProcessFailureModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-native-e011-")
        self.db_path = str(Path(self.temporary.name) / "receiver.sqlite3")
        self.process, self.url = start_receiver(self.db_path)

    def tearDown(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=5)
        self.temporary.cleanup()

    def restart_receiver(self):
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=5)
        self.process, self.url = start_receiver(self.db_path)

    def call(self, *, key="request-1", payload=None, **kwargs):
        return invoke(
            self.url,
            tenant="tenant-a",
            operation="ledger.post",
            key=key,
            payload={"amount": 7} if payload is None else payload,
            **kwargs,
        )

    def test_concurrent_duplicate_requests_from_independent_clients_apply_once(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(
                lambda _: self.call(),
                range(24),
            ))
        self.assertEqual({status for status, _ in responses}, {200})
        self.assertEqual(len({body["effect_id"] for _, body in responses}), 1)
        self.assertEqual(sum(not body["replayed"] for _, body in responses), 1)
        self.assertEqual(sum(body["replayed"] for _, body in responses), 23)
        self.assertEqual(effect_count(self.db_path), 1)

    def test_same_key_with_different_payload_is_conflict(self):
        status, _ = self.call(payload={"amount": 7})
        self.assertEqual(status, 200)
        status, body = self.call(payload={"amount": 8})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "idempotency_payload_conflict")
        self.assertEqual(effect_count(self.db_path), 1)

    def test_crash_after_commit_is_reconciled_after_process_restart(self):
        with self.assertRaises((URLError, RemoteDisconnected, ConnectionError, OSError)):
            self.call(crash_after_commit=True)
        self.process.join(timeout=5)
        self.assertFalse(self.process.is_alive())
        self.assertEqual(effect_count(self.db_path), 1)

        self.restart_receiver()
        status, body = self.call()
        self.assertEqual(status, 200)
        self.assertTrue(body["replayed"])
        self.assertEqual(effect_count(self.db_path), 1)

    def test_precommit_failure_rolls_back_effect_and_same_key_can_retry(self):
        status, body = self.call(fail_before_commit=True)
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], "injected_precommit_failure")
        self.assertEqual(effect_count(self.db_path), 0)

        status, body = self.call()
        self.assertEqual(status, 200)
        self.assertFalse(body["replayed"])
        self.assertEqual(effect_count(self.db_path), 1)

    def test_tenant_assertion_and_capability_are_not_caller_authority(self):
        status, body = invoke(
            self.url,
            tenant="tenant-a",
            operation="ledger.post",
            key="tenant-mismatch",
            payload={"amount": 1},
            principal="service-a",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["accepted"], True)

        # A caller cannot assert a different tenant in the request body.
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import json
        request = Request(
            f"{self.url}/invoke",
            data=json.dumps({
                "tenant_id": "tenant-b",
                "operation": "ledger.post",
                "payload": {"amount": 1},
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Principal": "service-a",
                "X-Tenant": "tenant-a",
                "X-Capability": "ledger.write",
                "Idempotency-Key": "forged-tenant",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(effect_count(self.db_path), 1)

        denied_status, denied = self.call(key="no-capability", capability="ledger.read")
        self.assertEqual(denied_status, 403)
        self.assertEqual(denied["error"], "capability_denied")
        self.assertEqual(effect_count(self.db_path), 1)


if __name__ == "__main__":
    unittest.main()
