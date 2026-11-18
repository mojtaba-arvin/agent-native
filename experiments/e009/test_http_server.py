from __future__ import annotations

import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import socketserver
from unittest import mock
from pathlib import Path

from audit import SQLiteAuditSink
from catalog import build_catalog_handlers
from http_server import create_server
from identity import MemoryIdentityProvider
from kernel import RuntimeRegistry, ServiceRuntime, load_service_ir
from repository import SQLiteCatalogRepository
from work_store import DurableWorkStore
from worker import CatalogWorker, OutboxRelay
from security_model import Grant, RequestContext


SOURCE = (Path(__file__).parent / "catalog.an").read_text(encoding="utf-8")
TRUSTED_EFFECTS = {"repository.read", "repository.write", "queue.submit", "queue.read", "queue.cancel"}


def make_context(principal, tenant, grants=True):
    capabilities = ("items.read", "items.create", "jobs.submit", "jobs.read", "jobs.cancel") if grants else ()
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


class KernelHTTPServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = SQLiteCatalogRepository(
            Path(self.temporary.name) / "http.sqlite3"
        )
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
        self.identity = MemoryIdentityProvider({
            "test-token-aaaaaaaaaaaaaaaaaaaaaaaa": make_context("user-a", "tenant-a"),
            "other-token-bbbbbbbbbbbbbbbbbbbb": make_context("user-b", "tenant-b"),
            "restricted-token-cccccccccccccccc": make_context("restricted", "tenant-a", grants=False),
        })
        self.server = create_server(self.runtime, self.identity, max_concurrency=8)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.repository.close()
        self.temporary.cleanup()

    def request(self, method, path, *, body=None, token="test-token-aaaaaaaaaaaaaaaaaaaaaaaa", headers=None):
        data = None if body is None else json.dumps(body, allow_nan=True).encode("utf-8")
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, error.headers, json.loads(error.read())

    def raw_request(self, payload: bytes):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5) as connection:
            connection.sendall(payload)
            connection.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                block = connection.recv(65536)
                if not block:
                    break
                chunks.append(block)
        raw = b"".join(chunks)
        head, _, body = raw.partition(b"\r\n\r\n")
        status = int(head.split(b"\r\n", 1)[0].split()[1])
        return status, head.decode("latin-1"), body


    def test_unauthenticated_http_request_is_audited_without_identity_claims(self):
        status, _headers, body = self.request("GET", "/items", token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "UNAUTHENTICATED")
        events = self.audit_sink.list_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertIsNone(event["principal_id"])
        self.assertIsNone(event["tenant_id"])
        self.assertEqual(event["operation"], "unauthenticated.get")
        self.assertEqual(event["resource"], "/items")
        self.assertEqual(event["requested_effects"], [])
        self.assertEqual(event["decision"], "deny")
        self.assertEqual(event["reason_code"], "UNAUTHENTICATED")

    def test_listen_backlog_is_set_before_socket_activation(self):
        observed_backlogs = []
        original_activate = socketserver.TCPServer.server_activate

        def capture_backlog(server):
            observed_backlogs.append(server.request_queue_size)
            return original_activate(server)

        with mock.patch.object(socketserver.TCPServer, "server_activate", capture_backlog):
            server = create_server(self.runtime, self.identity, max_concurrency=17)
        try:
            self.assertEqual(observed_backlogs, [17])
            self.assertEqual(server.request_queue_size, 17)
        finally:
            server.server_close()

    def test_non_loopback_binding_requires_explicit_host_opt_in(self):
        with self.assertRaisesRegex(ValueError, "must_be_loopback"):
            create_server(self.runtime, self.identity, host="0.0.0.0")
        server = create_server(
            self.runtime, self.identity, host="0.0.0.0", allow_non_loopback=True
        )
        try:
            self.assertEqual(server.server_address[0], "0.0.0.0")
        finally:
            server.server_close()

    def test_http_request_uses_one_published_runtime_revision(self):
        registry = RuntimeRegistry(self.runtime, revision=7)
        server = create_server(registry, self.identity, max_concurrency=8)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        previous_base = self.base_url
        self.base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            first_status, first_headers, _first_body = self.request("GET", "/items/by-name/not-found")
            self.assertEqual(first_status, 404)
            self.assertEqual(first_headers.get("X-Runtime-Revision"), "7")

            registry.publish(self.runtime, revision=8)
            second_status, second_headers, _second_body = self.request("GET", "/items/by-name/not-found")
            self.assertEqual(second_status, 404)
            self.assertEqual(second_headers.get("X-Runtime-Revision"), "8")
        finally:
            self.base_url = previous_base
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_real_http_create_get_by_id_and_get_by_name(self):
        status, headers, created = self.request(
            "POST",
            "/items",
            body={"name": "DeskLamp"},
            headers={"Idempotency-Key": "http-create-001"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["data"]["name"], "DeskLamp")
        self.assertTrue(headers.get("X-Request-ID"))
        item_id = created["data"]["id"]

        get_status, _get_headers, fetched = self.request("GET", f"/items/{item_id}")
        by_name_status, _by_name_headers, by_name = self.request(
            "GET", "/items/by-name/DeskLamp"
        )
        self.assertEqual(get_status, 200)
        self.assertEqual(by_name_status, 200)
        self.assertEqual(fetched["data"], created["data"])
        self.assertEqual(by_name["data"], created["data"])

    def test_client_supplied_identity_claims_never_override_authenticated_context(self):
        status, _headers, body = self.request(
            "POST",
            "/items",
            body={
                "name": "Forged tenant item",
                "tenant_id": "tenant-b",
                "principal_id": "attacker",
                "grants": ["items.create", "admin"],
            },
            headers={
                "X-Tenant-ID": "tenant-b",
                "X-Principal-ID": "attacker",
                "X-Capabilities": "admin",
                "Idempotency-Key": "forged-identity-001",
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "InvalidInput")
        self.assertIsNone(self.repository.get_item_by_name(
            tenant_id="tenant-a", name="Forged tenant item"
        ))
        self.assertIsNone(self.repository.get_item_by_name(
            tenant_id="tenant-b", name="Forged tenant item"
        ))

    def test_untrusted_identity_headers_are_ignored_when_body_is_valid(self):
        status, _headers, body = self.request(
            "POST",
            "/items",
            body={"name": "Authenticated tenant item"},
            headers={
                "X-Tenant-ID": "tenant-b",
                "X-Principal-ID": "attacker",
                "X-Capabilities": "admin",
                "Idempotency-Key": "identity-header-ignored-001",
            },
        )
        self.assertEqual(status, 201)
        self.assertIsNotNone(self.repository.get_item_by_name(
            tenant_id="tenant-a", name="Authenticated tenant item"
        ))
        self.assertIsNone(self.repository.get_item_by_name(
            tenant_id="tenant-b", name="Authenticated tenant item"
        ))

    def test_http_submission_creates_durable_job_and_is_idempotent(self):
        first = self.request(
            "POST",
            "/items/rebuild",
            body={},
            headers={"Idempotency-Key": "http-rebuild-001"},
        )
        second = self.request(
            "POST",
            "/items/rebuild",
            body={},
            headers={"Idempotency-Key": "http-rebuild-001"},
        )
        self.assertEqual(first[0], 202)
        self.assertEqual(first[2]["data"]["state"], "queued")
        self.assertEqual(second[0], 200)
        self.assertEqual(first[2]["data"], second[2]["data"])
        job = self.work_store.get_job(
            tenant_id="tenant-a",
            task_id=first[2]["data"]["id"],
        )
        self.assertEqual(job["state"], "queued")

    def test_http_submit_inspect_worker_complete_and_outbox_relay(self):
        submitted = self.request(
            "POST", "/items/rebuild", body={},
            headers={"Idempotency-Key": "http-lifecycle-001"},
        )
        self.assertEqual(submitted[0], 202)
        task_id = submitted[2]["data"]["id"]

        queued = self.request("GET", f"/jobs/{task_id}")
        self.assertEqual(queued[0], 200)
        self.assertEqual(queued[2]["data"]["state"], "queued")

        self.repository.create_item(
            tenant_id="tenant-a", name="Desk lamp",
            idempotency_key="worker-fixture-001", now=100,
        )
        worker = CatalogWorker(self.repository, self.work_store, lease_seconds=30)
        outcome = worker.run_once(worker_id="http-worker-1", now=101)
        self.assertEqual(outcome.task_id, task_id)
        self.assertEqual(outcome.state, "completed")
        self.assertEqual(outcome.result["items_seen"], 1)

        completed = self.request("GET", f"/jobs/{task_id}")
        self.assertEqual(completed[0], 200)
        self.assertEqual(completed[2]["data"]["state"], "completed")

        relay = OutboxRelay(self.work_store, consumer_id="http-observer")
        # The first pending event is work.submitted, then work.completed.
        first = relay.run_once(relay_id="http-relay", now=102)
        second = relay.run_once(relay_id="http-relay", now=103)
        self.assertTrue(first.claimed)
        self.assertTrue(second.claimed)
        self.assertEqual(
            self.work_store.consumer_total(
                consumer_id="http-observer",
                state_key="catalog.rebuild",
            ),
            1,
        )

    def test_http_running_job_cancel_requires_worker_stop_ack(self):
        submitted = self.request(
            "POST", "/items/rebuild", body={},
            headers={"Idempotency-Key": "http-cancel-running-001"},
        )
        task_id = submitted[2]["data"]["id"]
        claim = self.work_store.claim_job(
            worker_id="cancel-worker",
            now=101,
            lease_seconds=30,
        )
        self.assertEqual(claim["task_id"], task_id)
        request = self.request("POST", f"/jobs/{task_id}/cancel")
        self.assertEqual(request[0], 202)
        self.assertEqual(request[2]["data"]["state"], "cancellation_requested")
        still_running = self.work_store.get_job(tenant_id="tenant-a", task_id=task_id)
        self.assertEqual(still_running["lease_owner"], "cancel-worker")
        self.work_store.acknowledge_stopped(
            task_id=task_id,
            worker_id="cancel-worker",
            lease_token=claim["lease_token"],
            now=102,
        )
        final = self.request("GET", f"/jobs/{task_id}")
        self.assertEqual(final[2]["data"]["state"], "cancelled")

    def test_replayed_idempotency_key_returns_original_item(self):
        first = self.request(
            "POST", "/items", body={"name": "Replay"},
            headers={"Idempotency-Key": "http-replay-001"},
        )
        second = self.request(
            "POST", "/items", body={"name": "Replay"},
            headers={"Idempotency-Key": "http-replay-001"},
        )
        self.assertEqual(first[0], 201)
        self.assertEqual(second[0], 200)
        self.assertEqual(first[2]["data"], second[2]["data"])
        self.assertEqual(second[1].get("Idempotency-Replayed"), "true")

    def test_authentication_and_capability_authorization_are_distinct(self):
        unauthenticated = self.request("GET", "/items/by-name/DeskLamp", token=None)
        authenticated_but_denied = self.request(
            "POST",
            "/items",
            body={"name": "No permission"},
            token="restricted-token-cccccccccccccccc",
            headers={"Idempotency-Key": "http-denied-001"},
        )
        self.assertEqual(unauthenticated[0], 401)
        self.assertEqual(unauthenticated[2]["error"]["code"], "UNAUTHENTICATED")
        self.assertEqual(authenticated_but_denied[0], 403)
        self.assertEqual(authenticated_but_denied[2]["error"]["code"], "Unauthorized")

    def test_body_size_content_type_and_json_are_strict(self):
        too_large = self.raw_request(
            b"POST /items HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{self.server.server_port}\r\n".encode()
            + b"Authorization: Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa\r\n"
            + b"Content-Type: application/json\r\n"
            + b"Content-Length: 1048577\r\n"
            + b"Connection: close\r\n\r\n"
        )
        self.assertEqual(too_large[0], 413)
        too_large_body = json.loads(too_large[2].decode("utf-8"))
        self.assertEqual(too_large_body["error"]["code"], "BODY_TOO_LARGE")

        unsupported_media = self.raw_request(
            b"POST /items HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{self.server.server_port}\r\n".encode()
            + b"Authorization: Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa\r\n"
            + b"Content-Type: text/plain\r\n"
            + b"Content-Length: 2\r\nConnection: close\r\n\r\n{}"
        )
        self.assertEqual(unsupported_media[0], 415)

        duplicate_json = self.raw_request(
            b"POST /items HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{self.server.server_port}\r\n".encode()
            + b"Authorization: Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa\r\n"
            + b"Content-Type: application/json\r\n"
            + b"Idempotency-Key: http-json-001\r\n"
            + b"Content-Length: 27\r\nConnection: close\r\n\r\n"
            + b'{"name":"one","name":"two"}'
        )
        self.assertEqual(duplicate_json[0], 400)
        self.assertIn("INVALID_JSON", duplicate_json[2].decode("utf-8"))

    def test_duplicate_headers_and_chunked_encoding_are_rejected(self):
        duplicated = self.raw_request(
            b"POST /items HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{self.server.server_port}\r\n".encode()
            + b"Authorization: Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa\r\n"
            + b"authorization: Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa\r\n"
            + b"Content-Type: application/json\r\n"
            + b"Content-Length: 2\r\nConnection: close\r\n\r\n{}"
        )
        chunked = self.raw_request(
            b"POST /items HTTP/1.1\r\n"
            + f"Host: 127.0.0.1:{self.server.server_port}\r\n".encode()
            + b"Authorization: Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa\r\n"
            + b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        )
        self.assertEqual(duplicated[0], 400)
        self.assertIn("INVALID_HEADERS", duplicated[2].decode("utf-8"))
        self.assertEqual(chunked[0], 400)
        self.assertIn("TRANSFER_ENCODING_UNSUPPORTED", chunked[2].decode("utf-8"))

    def test_route_and_method_diagnostics_are_stable(self):
        missing = self.request("GET", "/does-not-exist")
        mismatch = self.request("DELETE", "/items")
        self.assertEqual(missing[0], 404)
        self.assertEqual(missing[2]["error"]["code"], "ROUTE_NOT_FOUND")
        self.assertEqual(mismatch[0], 405)
        self.assertEqual(mismatch[2]["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_bounded_admission_returns_503_when_capacity_is_exhausted(self):
        entered = threading.Event()
        release = threading.Event()
        item, _ = self.repository.create_item(
            tenant_id="tenant-a",
            name="Blocking",
            idempotency_key="blocking-001",
            now=100,
        )
        handlers = build_catalog_handlers(self.repository)
        original = handlers["get_item"]

        def blocking_handler(context):
            entered.set()
            release.wait(timeout=5)
            return original(context)

        handlers["get_item"] = blocking_handler
        runtime = ServiceRuntime(
            load_service_ir(SOURCE),
            handlers=handlers,
            repository=self.repository,
            trusted_effects=TRUSTED_EFFECTS,
            clock=lambda: 100,
        )
        server = create_server(runtime, self.identity, max_concurrency=1)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        first_result = {}

        def first_request():
            request = urllib.request.Request(
                base + f"/items/{item['id']}",
                headers={"Authorization": "Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    first_result["status"] = response.status
            except Exception as error:
                first_result["error"] = repr(error)

        request_thread = threading.Thread(target=first_request)
        request_thread.start()
        try:
            self.assertTrue(entered.wait(timeout=3))
            second = urllib.request.Request(
                base + f"/items/{item['id']}",
                headers={"Authorization": "Bearer test-token-aaaaaaaaaaaaaaaaaaaaaaaa"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(second, timeout=3) as response:
                    second_status = response.status
                    second_body = response.read()
            except urllib.error.HTTPError as error:
                second_status = error.code
                second_body = error.read()
            self.assertEqual(second_status, 503)
            self.assertIn(b"OVERLOADED", second_body)
        finally:
            release.set()
            request_thread.join(timeout=5)
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(first_result.get("status"), 200)


if __name__ == "__main__":
    unittest.main()
