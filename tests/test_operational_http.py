from __future__ import annotations

import http.client
import json
import threading
import unittest

from agent_native.operations import create_operational_server
from agent_native.runtime import RuntimeResponse


class StubServiceHost:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def dispatch_authenticated(
        self, service_id, method, target, body, *,
        authorization, headers=None, request_id=None,
    ):
        self.calls.append({
            "service_id": service_id,
            "method": method,
            "target": target,
            "body": body,
            "authorization": authorization,
            "headers": headers or {},
            "request_id": request_id,
        })
        if self.block:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("test request was not released")
        return RuntimeResponse(200, {
            "service_id": service_id,
            "target": target,
            "body": body,
        })


class OperationalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.host = StubServiceHost()
        self.server = create_operational_server(
            self.host,
            max_concurrency=8,
            max_request_body_bytes=16,
            request_timeout_seconds=1.0,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
        )
        self.thread.start()
        self.assertTrue(self.server._serve_started.wait(timeout=2))
        self.base_url = ("127.0.0.1", self.server.server_port)

    def tearDown(self):
        self.host.release.set()
        self.server.shutdown_gracefully(timeout_seconds=2)
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, *, body=None, authorization="Bearer test-token"):
        connection = http.client.HTTPConnection(*self.base_url, timeout=3)
        headers = {}
        if authorization is not None:
            headers["Authorization"] = authorization
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            content_type = response.getheader("Content-Type", "")
            value = json.loads(raw) if "application/json" in content_type and raw else raw.decode("utf-8")
            return response.status, response.getheaders(), value
        finally:
            connection.close()

    def test_health_and_readiness_change_during_shutdown(self):
        live_status, _headers, live = self.request("GET", "/health/live", authorization=None)
        ready_status, _headers, ready = self.request("GET", "/health/ready", authorization=None)
        self.assertEqual((live_status, live["status"]), (200, "live"))
        self.assertEqual((ready_status, ready["status"]), (200, "ready"))

        self.server.begin_draining()
        ready_status, _headers, ready = self.request("GET", "/health/ready", authorization=None)
        live_status, _headers, live = self.request("GET", "/health/live", authorization=None)
        self.assertEqual((ready_status, ready["status"]), (503, "not_ready"))
        self.assertEqual((live_status, live["status"]), (200, "live"))

    def test_application_route_uses_authenticated_host_dispatch(self):
        status, headers, body = self.request(
            "GET", "/catalog/items/by-name/Desk%20lamp?active=true",
            authorization="Bearer signed-token",
        )
        self.assertEqual(status, 200)
        self.assertTrue(dict(headers).get("X-Request-ID"))
        self.assertEqual(body["service_id"], "catalog")
        self.assertEqual(body["target"], "/items/by-name/Desk%20lamp?active=true")
        self.assertEqual(self.host.calls[0]["authorization"], "Bearer signed-token")
        self.assertEqual(self.host.calls[0]["request_id"], dict(headers)["X-Request-ID"])

    def test_metrics_count_requests_and_expose_inflight(self):
        status, _headers, _body = self.request("GET", "/catalog/items")
        self.assertEqual(status, 200)
        status, headers, metrics = self.request("GET", "/metrics", authorization=None)
        self.assertEqual(status, 200)
        self.assertIn("text/plain", dict(headers)["Content-Type"])
        self.assertIn("agent_native_http_requests_total", metrics)
        self.assertIn('method="GET",status="200"', metrics)
        self.assertIn("agent_native_http_in_flight_requests", metrics)
        self.assertIn("agent_native_http_rejected_requests_total", metrics)

    def test_body_limit_rejects_before_dispatch(self):
        status, _headers, body = self.request(
            "POST", "/catalog/items", body={"name": "this body is larger than sixteen bytes"},
        )
        self.assertEqual(status, 413)
        self.assertEqual(body["error"]["code"], "BODY_TOO_LARGE")
        self.assertEqual(self.host.calls, [])

    def test_concurrency_limit_returns_503(self):
        host = StubServiceHost()
        host.block = True
        server = create_operational_server(
            host,
            max_concurrency=1,
            max_request_body_bytes=128,
            request_timeout_seconds=3,
        )
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        serving.start()
        self.assertTrue(server._serve_started.wait(timeout=2))
        result = {}

        def first_request():
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
            try:
                connection.request("GET", "/catalog/items", headers={"Authorization": "Bearer one"})
                response = connection.getresponse()
                result["first"] = (response.status, response.read())
            finally:
                connection.close()

        request_thread = threading.Thread(target=first_request)
        try:
            request_thread.start()
            self.assertTrue(host.entered.wait(timeout=2))
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            try:
                connection.request("GET", "/catalog/items", headers={"Authorization": "Bearer two"})
                response = connection.getresponse()
                self.assertEqual(response.status, 503)
                self.assertEqual(json.loads(response.read())["error"]["code"], "OVERLOADED")
            finally:
                connection.close()
            self.assertEqual(server.metrics._rejected, 1)
        finally:
            host.release.set()
            request_thread.join(timeout=3)
            server.shutdown_gracefully(timeout_seconds=2)
            serving.join(timeout=3)
        self.assertFalse(request_thread.is_alive())
        self.assertEqual(result["first"][0], 200)

    def test_graceful_shutdown_drains_inflight_request(self):
        self.host.block = True
        response_result = {}

        def send_request():
            response_result["value"] = self.request("GET", "/catalog/items")

        request_thread = threading.Thread(target=send_request)
        request_thread.start()
        self.assertTrue(self.host.entered.wait(timeout=2))
        shutdown_result = []

        def stop_server():
            shutdown_result.append(self.server.shutdown_gracefully(timeout_seconds=3))

        shutdown_thread = threading.Thread(target=stop_server)
        shutdown_thread.start()
        self.assertTrue(self.server._serve_stopped.wait(timeout=2))
        self.host.release.set()
        request_thread.join(timeout=3)
        shutdown_thread.join(timeout=3)
        self.assertFalse(request_thread.is_alive())
        self.assertFalse(shutdown_thread.is_alive())
        self.assertEqual(response_result["value"][0], 200)
        self.assertEqual(shutdown_result, [True])
        self.assertFalse(self.server.ready)
        self.assertFalse(self.server.live)

    def test_configuration_rejects_unbounded_or_invalid_limits(self):
        with self.assertRaisesRegex(ValueError, "max_concurrency"):
            create_operational_server(self.host, max_concurrency=0)
        with self.assertRaisesRegex(ValueError, "max_request_body_bytes"):
            create_operational_server(self.host, max_request_body_bytes=0)
        with self.assertRaisesRegex(ValueError, "request_timeout_seconds"):
            create_operational_server(self.host, request_timeout_seconds=float("inf"))
        with self.assertRaisesRegex(ValueError, "must_be_loopback"):
            create_operational_server(self.host, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
