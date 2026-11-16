import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_native import Parser
from http_server import StaticIdentityProvider, create_server
from runtime import ReferenceRuntime
from security_model import Grant, RequestContext


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "examples" / "catalog.an").read_text(encoding="utf-8")
TRUSTED_EFFECTS = {"repository.read", "repository.write"}


class ReferenceHTTPServerTests(unittest.TestCase):
    def setUp(self):
        runtime = ReferenceRuntime.from_source(SOURCE, trusted_effects=TRUSTED_EFFECTS)
        context = RequestContext(
            principal_id="user-1",
            tenant_id="tenant-a",
            now=100,
            grants=(
                Grant("user-1", "tenant-a", "items.read", "/items"),
                Grant("user-1", "tenant-a", "items.create", "/items"),
            ),
        )
        self.server = create_server(runtime, StaticIdentityProvider({"test-token": context}))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, *, body=None, token="test-token"):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            headers["content-type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_dsl_declares_real_http_create_and_get_routes(self):
        status, created = self.request("POST", "/items", body={"name": "Desk lamp"})
        self.assertEqual(status, 200)
        item_id = created["data"]["id"]
        status, fetched = self.request("GET", f"/items/{item_id}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["data"], created["data"])

    def test_missing_identity_is_unauthenticated(self):
        status, body = self.request("GET", "/items/00000000-0000-0000-0000-000000000001", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHENTICATED")

    def test_invalid_body_and_method_have_stable_http_errors(self):
        status, body = self.request("POST", "/items", body={"name": "  "})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "InvalidInput")
        status, body = self.request("DELETE", "/items")
        self.assertEqual(status, 405)
        self.assertEqual(body["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_unknown_route_is_not_found(self):
        status, body = self.request("GET", "/unknown")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "ROUTE_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
