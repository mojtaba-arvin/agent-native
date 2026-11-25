from __future__ import annotations

import json
import os
import subprocess
import time
import unittest
import urllib.error
import urllib.request
import uuid

from agent_native import CapabilityTokenAuthority, Grant


BASE_URL = os.environ.get("T18_BASE_URL")
SIGNING_KEY_HEX = os.environ.get("T18_TOKEN_SIGNING_KEY_HEX")
PROJECT = os.environ.get("T18_COMPOSE_PROJECT")
COMPOSE_FILE = os.environ.get("T18_COMPOSE_FILE")


class PostgresContainerPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = (BASE_URL, SIGNING_KEY_HEX, PROJECT, COMPOSE_FILE)
        if any(not value for value in required):
            raise unittest.SkipTest("requires the live T18 disposable PostgreSQL pilot")
        try:
            signing_key = bytes.fromhex(SIGNING_KEY_HEX)
        except ValueError as error:
            raise unittest.SkipTest("T18 signing key must be hexadecimal") from error
        if len(signing_key) < 32:
            raise unittest.SkipTest("T18 signing key must contain at least 32 bytes")
        cls.authority = CapabilityTokenAuthority(signing_key)

    def token(self, tenant: str) -> str:
        principal = "principal-" + tenant
        grants = (
            Grant(principal, tenant, "items.read", "/items"),
            Grant(principal, tenant, "items.create", "/items"),
        )
        return self.authority.issue_token(principal, tenant, grants, ttl_seconds=240)

    def request(self, method: str, path: str, *, tenant: str | None = "tenant-a",
                body: dict | None = None, token: str | None = None,
                idempotency_key: str | None = None):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        elif tenant is not None:
            headers["Authorization"] = "Bearer " + self.token(tenant)
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        payload = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(BASE_URL + path, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            return error.code, json.loads(raw) if raw else None

    def create_item(self, *, tenant: str = "tenant-a") -> dict:
        status, payload = self.request(
            "POST", "/catalog/items", tenant=tenant,
            body={"name": "t18-" + uuid.uuid4().hex},
            idempotency_key="t18-" + uuid.uuid4().hex,
        )
        self.assertEqual(status, 201, payload)
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload.get("data"), dict)
        return payload["data"]

    def test_create_read_and_audit_are_durable(self):
        item = self.create_item()
        status, payload = self.request("GET", "/catalog/items/" + item["id"])
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["data"], item)

        code = (
            "import json, os, psycopg; "
            "db=psycopg.connect(os.environ['AGENT_NATIVE_POSTGRES_DSN']); "
            "schema=os.environ['AGENT_NATIVE_POSTGRES_SCHEMA']; "
            "cur=db.cursor(); "
            "cur.execute(f'SELECT count(*) FROM {schema}.audit_log WHERE tenant_id=%s', ('tenant-a',)); audit=cur.fetchone()[0]; "
            "cur.execute(f'SELECT count(*) FROM {schema}.outbox WHERE tenant_id=%s', ('tenant-a',)); outbox=cur.fetchone()[0]; "
            "cur.execute(f'SELECT count(*) FROM {schema}.idempotency_keys WHERE tenant_id=%s', ('tenant-a',)); idem=cur.fetchone()[0]; "
            "print(json.dumps({'audit':audit,'outbox':outbox,'idempotency':idem})); db.close()"
        )
        result = subprocess.run(
            ["docker", "compose", "--project-name", PROJECT, "--file", COMPOSE_FILE,
             "exec", "-T", "app", "python", "-c", code],
            check=True, capture_output=True, text=True, timeout=15,
        )
        counts = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertGreaterEqual(counts["audit"], 1)
        self.assertGreaterEqual(counts["outbox"], 1)
        self.assertGreaterEqual(counts["idempotency"], 1)

    def test_cross_tenant_resource_is_not_visible(self):
        item = self.create_item(tenant="tenant-a")
        status, payload = self.request(
            "GET", "/catalog/items/" + item["id"], tenant="tenant-b"
        )
        self.assertEqual(status, 404, payload)

    def test_health_readiness_and_metrics(self):
        for path in ("/health/live", "/health/ready"):
            status, _payload = self.request("GET", path, tenant=None)
            self.assertEqual(status, 200, path)
        request = urllib.request.Request(BASE_URL + "/metrics", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            metrics = response.read().decode("utf-8")
        self.assertIn("agent_native_http_requests_total", metrics)
        self.assertIn("agent_native_http_ready 1", metrics)

    def test_missing_and_invalid_tokens_fail_closed(self):
        status, _payload = self.request(
            "GET", "/catalog/items/by-name/not-used", tenant=None
        )
        self.assertEqual(status, 401)
        status, _payload = self.request(
            "GET", "/catalog/items/by-name/not-used", tenant=None, token="not-a-valid-token"
        )
        self.assertEqual(status, 401)

    def test_postgres_persists_across_container_restart(self):
        item = self.create_item()
        subprocess.run(
            ["docker", "compose", "--project-name", PROJECT, "--file", COMPOSE_FILE,
             "restart", "app"],
            check=True, capture_output=True, text=True, timeout=30,
        )
        deadline = time.monotonic() + 30
        last_error = None
        while time.monotonic() < deadline:
            try:
                status, payload = self.request("GET", "/health/ready", tenant=None)
                if status == 200:
                    break
            except (OSError, urllib.error.URLError) as error:
                last_error = error
            time.sleep(0.25)
        else:
            self.fail(f"application did not become ready after restart: {last_error}")
        status, payload = self.request("GET", "/catalog/items/" + item["id"])
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["data"], item)


if __name__ == "__main__":
    unittest.main(verbosity=2)
