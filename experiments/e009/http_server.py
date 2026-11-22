"""Bounded loopback HTTP host for the E-009 kernel prototype."""

from __future__ import annotations

import json
import math
import socket
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from identity import IdentityProvider
from kernel import RuntimeRegistry, RuntimeResponse, ServiceRuntime


MAX_REQUEST_BODY_BYTES = 1_048_576
DEFAULT_REQUEST_READ_TIMEOUT_SECONDS = 5.0


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ValueError("non_finite_json_number")


def _json_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Thread-per-connection host with explicit bounded admission/backpressure."""

    daemon_threads = False
    block_on_close = True

    def __init__(
        self,
        server_address,
        request_handler,
        *,
        max_concurrency: int,
        request_read_timeout: float,
    ):
        if type(max_concurrency) is not int or max_concurrency < 1:
            raise ValueError("max_concurrency_must_be_positive_integer")
        if (
            isinstance(request_read_timeout, bool)
            or not isinstance(request_read_timeout, (int, float))
            or not math.isfinite(request_read_timeout)
            or request_read_timeout <= 0
        ):
            raise ValueError("request_read_timeout_must_be_positive_finite_number")
        self.max_concurrency = max_concurrency
        self.request_read_timeout = float(request_read_timeout)
        # TCPServer calls listen(request_queue_size) inside super().__init__;
        # set the backlog before socket activation, not after construction.
        self.request_queue_size = max_concurrency
        self._admission = threading.BoundedSemaphore(max_concurrency)
        super().__init__(server_address, request_handler)

    def process_request(self, request: socket.socket, client_address) -> None:
        if not self._admission.acquire(blocking=False):
            payload = _json_bytes({"error": {"code": "OVERLOADED"}})
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json\r\n"
                b"Connection: close\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("ascii")
                + b"\r\n"
                + payload
            )
            try:
                request.sendall(response)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            # Bound request-line, header, and body reads before the handler thread
            # enters BaseHTTPRequestHandler's synchronous parser.
            request.settimeout(self.request_read_timeout)
            super().process_request(request, client_address)
        except Exception:
            self._admission.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._admission.release()


def create_server(
    runtime: ServiceRuntime | RuntimeRegistry,
    identity_provider: IdentityProvider,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_concurrency: int = 64,
    request_read_timeout: float = DEFAULT_REQUEST_READ_TIMEOUT_SECONDS,
    allow_non_loopback: bool = False,
) -> BoundedThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"} and not allow_non_loopback:
        raise ValueError("e009_http_host_must_be_loopback")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid_http_port")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args) -> None:
            return

        def _send(self, status: int, payload: dict, *, request_id: str, headers=None) -> None:
            encoded = _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.send_header("X-Request-ID", request_id)
            # The same root correlation identifier is persisted in audit_events.request_id.
            self.send_header("X-Trace-ID", request_id)
            revision = getattr(self, "_runtime_revision", None)
            if revision is not None:
                self.send_header("X-Runtime-Revision", str(revision))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

        def _request_headers(self) -> dict[str, str] | None:
            result = {}
            for key, value in self.headers.items():
                normalized = key.lower()
                if normalized in result:
                    return None
                result[normalized] = value
            return result

        def _dispatch(self, method: str) -> None:
            snapshot = runtime.snapshot() if isinstance(runtime, RuntimeRegistry) else None
            active_runtime = snapshot.runtime if snapshot is not None else runtime
            self._runtime_revision = snapshot.revision if snapshot is not None else None
            request_id = str(uuid.uuid4())
            headers = self._request_headers()
            if headers is None:
                self._send(400, {"error": {"code": "INVALID_HEADERS"}}, request_id=request_id)
                return

            identity = identity_provider.authenticate(headers.get("authorization"))
            if identity is None:
                if active_runtime.audit_sink is not None:
                    try:
                        timestamp = active_runtime.clock()
                        if type(timestamp) is not int or timestamp < 0:
                            raise ValueError("invalid_audit_clock")
                        active_runtime.audit_sink({
                            "principal_id": None,
                            "tenant_id": None,
                            "operation": f"unauthenticated.{method.lower()}",
                            "resource": self.path,
                            "requested_effects": [],
                            "decision": "deny",
                            "reason_code": "UNAUTHENTICATED",
                            "request_id": request_id,
                            "timestamp": timestamp,
                        })
                    except Exception:
                        self._send(503, {"error": {"code": "AUDIT_UNAVAILABLE"}}, request_id=request_id)
                        return
                self._send(401, {"error": {"code": "UNAUTHENTICATED"}}, request_id=request_id)
                return

            if "transfer-encoding" in headers:
                self._send(400, {"error": {"code": "TRANSFER_ENCODING_UNSUPPORTED"}}, request_id=request_id)
                return

            body = {}
            if method in {"POST", "PUT", "PATCH"}:
                raw_length = headers.get("content-length")
                if raw_length is None or not raw_length.isascii() or not raw_length.isdecimal():
                    self._send(400, {"error": {"code": "INVALID_CONTENT_LENGTH"}}, request_id=request_id)
                    return
                length = int(raw_length)
                if length > MAX_REQUEST_BODY_BYTES:
                    self._send(413, {"error": {"code": "BODY_TOO_LARGE"}}, request_id=request_id)
                    return
                if length and headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    self._send(415, {"error": {"code": "UNSUPPORTED_MEDIA_TYPE"}}, request_id=request_id)
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._send(400, {"error": {"code": "TRUNCATED_BODY"}}, request_id=request_id)
                    return
                try:
                    body = json.loads(
                        raw or b"{}",
                        object_pairs_hook=_reject_duplicate_keys,
                        parse_constant=_reject_non_finite,
                    )
                    if not isinstance(body, dict):
                        raise ValueError("body_must_be_object")
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    self._send(400, {"error": {"code": "INVALID_JSON"}}, request_id=request_id)
                    return
            else:
                raw_length = headers.get("content-length", "0")
                if raw_length not in {"0", ""}:
                    self._send(400, {"error": {"code": "BODY_NOT_ALLOWED"}}, request_id=request_id)
                    return

            # The read budget ends once the complete request is buffered; do not
            # impose the client-read timeout on application work or response writes.
            self.connection.settimeout(None)
            response: RuntimeResponse = active_runtime.dispatch(
                method,
                self.path,
                body,
                identity,
                headers=headers,
                request_id=request_id,
            )
            self._send(
                response.status_code,
                response.body,
                request_id=request_id,
                headers=response.headers,
            )

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def do_HEAD(self) -> None:
            self._dispatch("HEAD")

        def do_OPTIONS(self) -> None:
            self._dispatch("OPTIONS")

    server = BoundedThreadingHTTPServer(
        (host, port),
        Handler,
        max_concurrency=max_concurrency,
        request_read_timeout=request_read_timeout,
    )
    return server
