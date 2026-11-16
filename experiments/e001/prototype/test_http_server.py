import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from agent_native import Parser
from http_server import MAX_REQUEST_BODY_BYTES, StaticIdentityProvider, create_server
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
        limited_context = RequestContext(
            principal_id="user-2",
            tenant_id="tenant-a",
            now=100,
            grants=(),
        )
        self.server = create_server(
            runtime,
            StaticIdentityProvider({"test-token": context, "limited-token": limited_context}),
        )
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

    def request_raw(self, method, path, raw_body, *, token="test-token"):
        headers = {"content-type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            self.base_url + path, data=raw_body, headers=headers, method=method
        )
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



    def test_unsupported_put_and_patch_return_method_not_allowed(self):
        for method in ("PUT", "PATCH"):
            status, body = self.request(method, "/items", body={"name": "Lamp"})
            self.assertEqual(status, 405)
            self.assertEqual(body["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_duplicate_json_keys_and_non_finite_numbers_are_rejected(self):
        for raw in (b'{"name":"one","name":"two"}', b'{"name":NaN}'):
            status, body = self.request_raw("POST", "/items", raw)
            self.assertEqual(status, 400)
            self.assertEqual(body["error"]["code"], "INVALID_JSON")

    def test_request_body_size_is_bounded(self):
        port = int(self.base_url.rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
            connection.settimeout(3)
            connection.sendall(
                (
                    "POST /items HTTP/1.1\\r\\n"
                    "Host: 127.0.0.1\\r\\n"
                    "Authorization: Bearer test-token\\r\\n"
                    f"Content-Length: {MAX_REQUEST_BODY_BYTES + 1}\\r\\n"
                    "Connection: close\\r\\n\\r\\n"
                ).encode("ascii")
            )
            response = b""
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response += chunk
        headers, raw_body = response.split(b"\\r\\n\\r\\n", 1)
        status = int(headers.split(b"\\r\\n", 1)[0].split()[1])
        body = json.loads(raw_body)
        self.assertEqual(status, 413)
        self.assertEqual(body["error"]["code"], "BODY_TOO_LARGE")


    def test_authenticated_principal_without_capability_is_forbidden(self):
        status, body = self.request(
            "GET", "/items/00000000-0000-0000-0000-000000000001",
            token="limited-token",
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "Unauthorized")

    def test_invalid_typed_path_input_uses_declared_invalid_input_error(self):
        status, body = self.request("GET", "/items/not-a-uuid")
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "InvalidInput")

if __name__ == "__main__":
    unittest.main()
