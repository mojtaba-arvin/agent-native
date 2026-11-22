from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProductControlPlaneIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="e002-product-workload-")
        self.database = Path(self.temporary.name) / "product.sqlite3"
        self.token = "e002-product-workload-token-aaaaaaaa"
        environment = {
            **os.environ,
            "AGENT_NATIVE_DEMO_TOKEN": self.token,
            "AGENT_NATIVE_PRODUCT_WORKLOAD": "1",
        }
        self.process = subprocess.Popen(
            [
                sys.executable, str(ROOT / "experiments/e009/serve.py"),
                "--database", str(self.database), "--port", "0",
                "--worker-poll-seconds", "0.05", "--relay-poll-seconds", "0.05",
            ],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        deadline = time.monotonic() + 15
        self.base = None
        startup = []
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if line:
                startup.append(line)
            if self.process.poll() is not None:
                self.fail("reference host exited during startup: " + "".join(startup))
            match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
            if match:
                self.base = f"http://127.0.0.1:{match.group(1)}"
                break
        self.assertIsNotNone(self.base, "reference host did not announce a loopback URL")
        self.base_revision = hashlib.sha256(
            (ROOT / "experiments/e009/catalog.an").read_bytes()
        ).hexdigest()

    def tearDown(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.temporary.cleanup()

    def request(self, path, token, body):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read())

    def test_validate_plan_is_authenticated_pinned_audited_and_non_mutating(self):
        status, headers, body = self.request(
            "/control/validate-plan",
            self.token,
            {"operation_name": "get_item", "base_revision": self.base_revision},
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["data"], {
            "valid": True,
            "will_mutate": False,
            "will_deploy": False,
            "operation": "get_item",
            "revision": self.base_revision,
        })
        self.assertEqual(headers.get("X-Request-ID"), headers.get("X-Request-ID"))

        stale_status, _, stale = self.request(
            "/control/validate-plan",
            self.token,
            {"operation_name": "get_item", "base_revision": "0" * 64},
        )
        self.assertEqual(stale_status, 400, stale)

        denied_status, denied_headers, denied = self.request(
            "/control/validate-plan",
            self.token + "-read-only",
            {"operation_name": "get_item", "base_revision": self.base_revision},
        )
        self.assertEqual(denied_status, 403, denied)
        self.assertEqual(denied["error"]["code"], "UNAUTHORIZED")
        self.assertEqual(denied_headers.get("X-Request-ID"), denied_headers.get("X-Request-ID"))

        connection = sqlite3.connect(self.database)
        try:
            events = connection.execute(
                "SELECT request_id, decision, reason_code FROM audit_events "
                "WHERE operation = 'plan_operation' ORDER BY event_id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual([event[1] for event in events], ["allow", "allow", "deny"])
        self.assertEqual(events[0][0], headers["X-Request-ID"])
        self.assertEqual(events[2][0], denied_headers["X-Request-ID"])
        self.assertEqual(events[2][2], "MISSING_CAPABILITY")


if __name__ == "__main__":
    unittest.main()
