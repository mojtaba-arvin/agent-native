"""Black-box HTTP conformance tests for the E-009 Python reference host.

Every assertion in this module observes the TCP/HTTP boundary. The setup
constructs the reference runtime, but tests do not inspect its repository,
audit tables, handlers, or worker state.
"""

from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from audit import SQLiteAuditSink
from catalog import build_catalog_handlers
from http_server import create_server
from identity import MemoryIdentityProvider
from kernel import ServiceRuntime, load_service_ir
from repository import SQLiteCatalogRepository
from work_store import DurableWorkStore
from security_model import Grant, RequestContext


E009_ROOT = Path(__file__).resolve().parent
SOURCE = (E009_ROOT / "catalog.an").read_text(encoding="utf-8")
TRUSTED_EFFECTS = {
    "repository.read",
    "repository.write",
    "queue.submit",
    "queue.read",
    "queue.cancel",
}
TOKEN_A = "test-token-aaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "other-token-bbbbbbbbbbbbbbbbbbbb"
RESTRICTED_TOKEN = "restricted-token-cccccccccccccccc"


def make_context(principal: str, tenant: str, *, grants: bool = True) -> RequestContext:
    capabilities = (
        ("items.read", "items.create", "jobs.submit", "jobs.read", "jobs.cancel")
        if grants
        else ()
    )
    return RequestContext(
        principal_id=principal,
        tenant_id=tenant,
        now=0,
        grants=tuple(
            Grant(
                principal,
                tenant,
                capability,
                "/jobs" if capability in {"jobs.read", "jobs.cancel"} else "/items",
            )
            for capability in capabilities
        ),
    )


class HTTPConformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        database = Path(self.temporary.name) / "http-conformance.sqlite3"
        self.repository = SQLiteCatalogRepository(database)
        self.audit_sink = SQLiteAuditSink(self.repository.database)
        self.work_store = DurableWorkStore(
            self.repository.database,
            audit_sink=self.audit_sink,
        )
        self.runtime = ServiceRuntime(
            load_service_ir(SOURCE),
            handlers=build_catalog_handlers(self.repository, self.work_store),
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: 100,
            audit_sink=self.audit_sink,
        )
        self.identity = MemoryIdentityProvider(
            {
                TOKEN_A: make_context("user-a", "tenant-a"),
                TOKEN_B: make_context("user-b", "tenant-b"),
                RESTRICTED_TOKEN: make_context(
                    "restricted-user", "tenant-a", grants=False
                ),
            }
        )
        self.server = create_server(self.runtime, self.identity, max_concurrency=8)
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.server_thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        self.repository.close()
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        token: str | None = TOKEN_A,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes, object]:
        data = (
            None
            if body is None
            else json.dumps(body, allow_nan=True, separators=(",", ":")).encode("utf-8")
        )
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                status = response.status
                response_headers = dict(response.headers.items())
                raw_body = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = dict(error.headers.items())
            raw_body = error.read()
        payload = json.loads(raw_body) if raw_body else None
        return status, response_headers, raw_body, payload

    def raw_request(
        self,
        method: str,
        path: str,
        *,
        headers: tuple[str, ...] = (),
        body: bytes = b"",
        include_content_length: bool = True,
        declared_content_length: int | None = None,
    ) -> tuple[int, dict[str, str], bytes, object]:
        lines = [
            f"{method} {path} HTTP/1.1",
            f"Host: 127.0.0.1:{self.server.server_port}",
            *headers,
        ]
        if include_content_length:
            length = (
                len(body)
                if declared_content_length is None
                else declared_content_length
            )
            lines.append(f"Content-Length: {length}")
        lines.append("Connection: close")
        wire = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body

        with socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=5
        ) as connection:
            connection.sendall(wire)
            connection.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                block = connection.recv(65536)
                if not block:
                    break
                chunks.append(block)

        response = b"".join(chunks)
        raw_headers, separator, raw_body = response.partition(b"\r\n\r\n")
        self.assertTrue(separator, "server response must contain an HTTP header block")
        header_lines = raw_headers.decode("latin-1").split("\r\n")
        status = int(header_lines[0].split()[1])
        response_headers = {}
        for line in header_lines[1:]:
            name, separator, value = line.partition(":")
            if separator:
                response_headers[name.strip().lower()] = value.strip()
        payload = json.loads(raw_body) if raw_body else None
        return status, response_headers, raw_body, payload

    def assert_http_contract(
        self,
        response: tuple[int, dict[str, str], bytes, object],
        *,
        request_id_in_body: bool | None = None,
    ) -> str:
        _status, headers, raw_body, payload = response
        self.assertEqual(
            headers.get("content-type", "").split(";", 1)[0],
            "application/json",
        )
        self.assertEqual(int(headers["content-length"]), len(raw_body))
        self.assertEqual(headers.get("connection"), "close")
        request_id = headers.get("x-request-id")
        self.assertIsNotNone(request_id)
        uuid.UUID(request_id)
        if isinstance(payload, dict) and "request_id" in payload:
            self.assertEqual(payload["request_id"], request_id)
        if request_id_in_body is not None and isinstance(payload, dict):
            self.assertEqual("request_id" in payload, request_id_in_body)
        return request_id

    def assert_error(
        self,
        response: tuple[int, dict[str, str], bytes, object],
        *,
        status: int,
        code: str,
        request_id_in_body: bool | None = None,
    ) -> dict:
        self.assertEqual(response[0], status)
        self.assert_http_contract(response, request_id_in_body=request_id_in_body)
        payload = response[3]
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("error"), {"code": code})
        return payload

    def test_create_and_read_follow_the_json_success_contract(self) -> None:
        created = self.request(
            "POST",
            "/items",
            body={"name": "Desk lamp"},
            headers={"Idempotency-Key": "t04-create-001"},
        )
        self.assertEqual(created[0], 201)
        create_request_id = self.assert_http_contract(created, request_id_in_body=True)
        created_payload = created[3]
        self.assertEqual(set(created_payload), {"data", "request_id"})
        self.assertEqual(set(created_payload["data"]), {"id", "name"})
        self.assertEqual(created_payload["data"]["name"], "Desk lamp")
        item_id = created_payload["data"]["id"]
        uuid.UUID(item_id)

        by_id = self.request("GET", f"/items/{item_id}")
        self.assertEqual(by_id[0], 200)
        self.assertNotEqual(
            self.assert_http_contract(by_id, request_id_in_body=True),
            create_request_id,
        )
        self.assertEqual(by_id[3]["data"], created_payload["data"])

        by_name = self.request("GET", "/items/by-name/Desk%20lamp")
        self.assertEqual(by_name[0], 200)
        self.assert_http_contract(by_name, request_id_in_body=True)
        self.assertEqual(by_name[3]["data"], created_payload["data"])

    def test_authentication_and_capability_denial_are_distinct(self) -> None:
        unauthenticated = self.request("GET", "/items", token=None)
        self.assert_error(
            unauthenticated,
            status=401,
            code="UNAUTHENTICATED",
            request_id_in_body=False,
        )

        authenticated_without_grant = self.request(
            "POST",
            "/items",
            body={"name": "Denied item"},
            token=RESTRICTED_TOKEN,
            headers={"Idempotency-Key": "t04-denied-001"},
        )
        self.assert_error(
            authenticated_without_grant,
            status=403,
            code="Unauthorized",
            request_id_in_body=True,
        )

    def test_route_and_method_failures_have_stable_diagnostics(self) -> None:
        missing_route = self.request("GET", "/not-a-catalog-route")
        self.assert_error(
            missing_route,
            status=404,
            code="ROUTE_NOT_FOUND",
            request_id_in_body=True,
        )

        wrong_method = self.request("DELETE", "/items")
        self.assert_error(
            wrong_method,
            status=405,
            code="METHOD_NOT_ALLOWED",
            request_id_in_body=True,
        )

    def test_item_lookup_does_not_disclose_another_tenants_record(self) -> None:
        created = self.request(
            "POST",
            "/items",
            body={"name": "Tenant A private item"},
            headers={"Idempotency-Key": "t04-tenant-001"},
        )
        self.assertEqual(created[0], 201)
        item_id = created[3]["data"]["id"]

        foreign_read = self.request("GET", f"/items/{item_id}", token=TOKEN_B)
        self.assert_error(
            foreign_read,
            status=404,
            code="NotFound",
            request_id_in_body=True,
        )

    def test_required_and_unknown_body_fields_fail_validation(self) -> None:
        missing_field = self.request(
            "POST",
            "/items",
            body={},
            headers={"Idempotency-Key": "t04-input-missing"},
        )
        self.assert_error(
            missing_field,
            status=400,
            code="InvalidInput",
            request_id_in_body=True,
        )

        empty_field = self.request(
            "POST",
            "/items",
            body={"name": "   "},
            headers={"Idempotency-Key": "t04-input-empty"},
        )
        self.assert_error(
            empty_field,
            status=400,
            code="InvalidInput",
            request_id_in_body=True,
        )

        unknown_field = self.request(
            "POST",
            "/items",
            body={"name": "Lamp", "is_admin": True},
            headers={"Idempotency-Key": "t04-input-extra"},
        )
        self.assert_error(
            unknown_field,
            status=400,
            code="InvalidInput",
            request_id_in_body=True,
        )

    def test_duplicate_and_unknown_query_fields_fail_closed(self) -> None:
        duplicate = self.request(
            "GET", "/items/by-name/DeskLamp?filter=a&filter=b"
        )
        self.assert_error(
            duplicate,
            status=400,
            code="InvalidInput",
            request_id_in_body=True,
        )

        unknown = self.request(
            "GET", "/items/by-name/DeskLamp?unexpected=value"
        )
        self.assert_error(
            unknown,
            status=400,
            code="InvalidInput",
            request_id_in_body=True,
        )

    def test_encoded_path_separators_and_invalid_escapes_are_rejected(self) -> None:
        for suffix in ("part%2Fother", "part%5Cother", "part%ZZ"):
            with self.subTest(suffix=suffix):
                response = self.request("GET", f"/items/by-name/{suffix}")
                self.assert_error(
                    response,
                    status=400,
                    code="InvalidInput",
                    request_id_in_body=True,
                )

    def test_idempotency_replay_and_payload_conflict_are_explicit(self) -> None:
        headers = {"Idempotency-Key": "t04-replay-001"}
        first = self.request(
            "POST", "/items", body={"name": "Replay lamp"}, headers=headers
        )
        self.assertEqual(first[0], 201)
        self.assert_http_contract(first, request_id_in_body=True)

        replay = self.request(
            "POST", "/items", body={"name": "Replay lamp"}, headers=headers
        )
        self.assertEqual(replay[0], 200)
        self.assertEqual(replay[1].get("Idempotency-Replayed"), "true")
        self.assert_http_contract(replay, request_id_in_body=True)
        self.assertEqual(replay[3]["data"], first[3]["data"])

        conflict = self.request(
            "POST", "/items", body={"name": "Different lamp"}, headers=headers
        )
        payload = self.assert_error(
            conflict,
            status=409,
            code="Conflict",
            request_id_in_body=True,
        )
        self.assertEqual(set(payload), {"error", "request_id"})
        self.assertEqual(set(payload["error"]), {"code"})

    def test_duplicate_json_keys_and_non_finite_numbers_are_rejected(self) -> None:
        request_headers = (
            f"Authorization: Bearer {TOKEN_A}",
            "Content-Type: application/json",
            "Idempotency-Key: t04-invalid-json",
        )
        for body in (
            b'{"name":"first","name":"second"}',
            b'{"name":NaN}',
            b'{"name":Infinity}',
        ):
            with self.subTest(body=body):
                response = self.raw_request(
                    "POST", "/items", headers=request_headers, body=body
                )
                self.assert_error(
                    response,
                    status=400,
                    code="INVALID_JSON",
                    request_id_in_body=False,
                )

    def test_json_body_must_be_an_object(self) -> None:
        response = self.raw_request(
            "POST",
            "/items",
            headers=(
                f"Authorization: Bearer {TOKEN_A}",
                "Content-Type: application/json",
                "Idempotency-Key: t04-json-root",
            ),
            body=b"[]",
        )
        self.assert_error(
            response,
            status=400,
            code="INVALID_JSON",
            request_id_in_body=False,
        )

    def test_media_type_and_content_length_failures_are_stable(self) -> None:
        unsupported_media = self.raw_request(
            "POST",
            "/items",
            headers=(
                f"Authorization: Bearer {TOKEN_A}",
                "Content-Type: text/plain",
                "Idempotency-Key: t04-media-type",
            ),
            body=b"{}",
        )
        self.assert_error(
            unsupported_media,
            status=415,
            code="UNSUPPORTED_MEDIA_TYPE",
            request_id_in_body=False,
        )

        missing_length = self.raw_request(
            "POST",
            "/items",
            headers=(
                f"Authorization: Bearer {TOKEN_A}",
                "Content-Type: application/json",
                "Idempotency-Key: t04-content-length",
            ),
            body=b"",
            include_content_length=False,
        )
        self.assert_error(
            missing_length,
            status=400,
            code="INVALID_CONTENT_LENGTH",
            request_id_in_body=False,
        )

    def test_oversized_body_is_rejected_before_reading_it(self) -> None:
        response = self.raw_request(
            "POST",
            "/items",
            headers=(
                f"Authorization: Bearer {TOKEN_A}",
                "Content-Type: application/json",
                "Idempotency-Key: t04-oversized",
            ),
            declared_content_length=1_048_577,
        )
        self.assert_error(
            response,
            status=413,
            code="BODY_TOO_LARGE",
            request_id_in_body=False,
        )

    def test_duplicate_headers_and_chunked_framing_are_rejected(self) -> None:
        duplicate_header = self.raw_request(
            "POST",
            "/items",
            headers=(
                f"Authorization: Bearer {TOKEN_A}",
                f"authorization: Bearer {TOKEN_A}",
                "Content-Type: application/json",
                "Idempotency-Key: t04-duplicate-header",
            ),
            body=b"{}",
        )
        self.assert_error(
            duplicate_header,
            status=400,
            code="INVALID_HEADERS",
            request_id_in_body=False,
        )

        chunked = self.raw_request(
            "POST",
            "/items",
            headers=(
                f"Authorization: Bearer {TOKEN_A}",
                "Transfer-Encoding: chunked",
                "Content-Type: application/json",
            ),
            include_content_length=False,
        )
        self.assert_error(
            chunked,
            status=400,
            code="TRANSFER_ENCODING_UNSUPPORTED",
            request_id_in_body=False,
        )

    def test_audit_failure_fails_closed_before_request_dispatch(self) -> None:
        def unavailable(_event: dict) -> None:
            raise OSError("audit store unavailable")

        self.runtime.audit_sink = unavailable
        response = self.request("GET", "/items", token=None)
        self.assert_error(
            response,
            status=503,
            code="AUDIT_UNAVAILABLE",
            request_id_in_body=False,
        )


if __name__ == "__main__":
    unittest.main()
