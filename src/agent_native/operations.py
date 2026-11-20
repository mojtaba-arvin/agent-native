"""Bounded HTTP ingress and operational endpoints for a ServiceHost."""

from __future__ import annotations

import json
import math
import re
import socket
import threading
import time
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit

from .runtime import RuntimeResponse


_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_SERVICE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ValueError("non_finite_json_number")


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class OperationalMetrics:
    """Thread-safe, low-cardinality HTTP counters and latency histogram."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[tuple[str, int]] = Counter()
        self._buckets = [0 for _ in _LATENCY_BUCKETS]
        self._duration_count = 0
        self._duration_sum = 0.0
        self._in_flight = 0
        self._rejected = 0
        self._shutdowns = 0

    def begin_request(self) -> None:
        with self._lock:
            self._in_flight += 1

    def end_request(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def record(self, method: str, status: int, duration_seconds: float) -> None:
        method = method if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER"
        with self._lock:
            self._requests[(method, status)] += 1
            self._duration_count += 1
            self._duration_sum += max(0.0, duration_seconds)
            for index, boundary in enumerate(_LATENCY_BUCKETS):
                if duration_seconds <= boundary:
                    self._buckets[index] += 1

    def reject(self) -> None:
        with self._lock:
            self._rejected += 1

    def shutdown(self) -> None:
        with self._lock:
            self._shutdowns += 1

    def render(self, *, ready: bool) -> str:
        with self._lock:
            requests = sorted(self._requests.items())
            buckets = tuple(self._buckets)
            count = self._duration_count
            total = self._duration_sum
            in_flight = self._in_flight
            rejected = self._rejected
            shutdowns = self._shutdowns

        lines = [
            "# HELP agent_native_http_requests_total Completed HTTP requests.",
            "# TYPE agent_native_http_requests_total counter",
        ]
        for (method, status), value in requests:
            lines.append(f'agent_native_http_requests_total{{method="{method}",status="{status}"}} {value}')
        lines.extend((
            "# HELP agent_native_http_request_duration_seconds HTTP request duration.",
            "# TYPE agent_native_http_request_duration_seconds histogram",
        ))
        for boundary, value in zip(_LATENCY_BUCKETS, buckets):
            lines.append(f'agent_native_http_request_duration_seconds_bucket{{le="{boundary:g}"}} {value}')
        lines.extend((
            f'agent_native_http_request_duration_seconds_bucket{{le="+Inf"}} {count}',
            f"agent_native_http_request_duration_seconds_sum {total:.9f}",
            f"agent_native_http_request_duration_seconds_count {count}",
            "# HELP agent_native_http_in_flight_requests Requests currently being handled.",
            "# TYPE agent_native_http_in_flight_requests gauge",
            f"agent_native_http_in_flight_requests {in_flight}",
            "# HELP agent_native_http_rejected_requests_total Requests rejected by admission control.",
            "# TYPE agent_native_http_rejected_requests_total counter",
            f"agent_native_http_rejected_requests_total {rejected}",
            "# HELP agent_native_http_ready Whether the server accepts ready traffic.",
            "# TYPE agent_native_http_ready gauge",
            f"agent_native_http_ready {1 if ready else 0}",
            "# HELP agent_native_http_shutdowns_total Graceful shutdown attempts.",
            "# TYPE agent_native_http_shutdowns_total counter",
            f"agent_native_http_shutdowns_total {shutdowns}",
            "",
        ))
        return "\n".join(lines)


class OperationalHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP ingress with bounded admission and graceful draining.

    Health and metrics endpoints are deliberately independent of application
    authentication. Application routes use /{service_id}/{service_path} and
    always cross ServiceHost.dispatch_authenticated.
    """

    allow_reuse_address = True
    daemon_threads = False
    block_on_close = False

    def __init__(
        self,
        server_address,
        request_handler,
        *,
        service_host,
        max_concurrency: int,
        max_request_body_bytes: int,
        request_timeout_seconds: float,
    ) -> None:
        if type(max_concurrency) is not int or max_concurrency < 1:
            raise ValueError("max_concurrency_must_be_positive_integer")
        if type(max_request_body_bytes) is not int or max_request_body_bytes < 1:
            raise ValueError("max_request_body_bytes_must_be_positive_integer")
        if (
            isinstance(request_timeout_seconds, bool)
            or not isinstance(request_timeout_seconds, (int, float))
            or not math.isfinite(request_timeout_seconds)
            or request_timeout_seconds <= 0
        ):
            raise ValueError("request_timeout_seconds_must_be_finite_and_positive")
        if not callable(getattr(service_host, "dispatch_authenticated", None)):
            raise TypeError("service_host_must_support_authenticated_dispatch")

        self.service_host = service_host
        self.max_concurrency = max_concurrency
        self.max_request_body_bytes = max_request_body_bytes
        self.request_timeout_seconds = float(request_timeout_seconds)
        self.request_queue_size = max_concurrency
        self.metrics = OperationalMetrics()
        self._admission = threading.BoundedSemaphore(max_concurrency)
        self._condition = threading.Condition()
        self._active_sockets: set[socket.socket] = set()
        self._active_requests = 0
        self._ready = True
        self._stopped = False
        self._serve_started = threading.Event()
        self._serve_stopped = threading.Event()
        super().__init__(server_address, request_handler)

    @property
    def ready(self) -> bool:
        with self._condition:
            return self._ready and not self._stopped

    @property
    def live(self) -> bool:
        with self._condition:
            return not self._stopped

    @property
    def active_requests(self) -> int:
        with self._condition:
            return self._active_requests

    def begin_draining(self) -> None:
        """Remove this instance from readiness before stopping the listener."""
        with self._condition:
            self._ready = False

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self._serve_started.set()
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            with self._condition:
                self._ready = False
                self._stopped = True
                self._condition.notify_all()
            self._serve_stopped.set()

    def _reject_connection(self, request: socket.socket, status: int, code: str) -> None:
        payload = _json_bytes({"error": {"code": code}})
        phrase = "Service Unavailable" if status == 503 else "Request Timeout"
        response = (
            f"HTTP/1.1 {status} {phrase}\r\n".encode("ascii")
            + b"Content-Type: application/json\r\n"
            + b"Connection: close\r\n"
            + f"Content-Length: {len(payload)}\r\n".encode("ascii")
            + b"\r\n"
            + payload
        )
        self.metrics.reject()
        try:
            request.sendall(response)
        except OSError:
            pass
        finally:
            self.shutdown_request(request)

    def process_request(self, request: socket.socket, client_address) -> None:
        if not self.ready:
            self._reject_connection(request, 503, "SERVER_DRAINING")
            return
        if not self._admission.acquire(blocking=False):
            self._reject_connection(request, 503, "OVERLOADED")
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._admission.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address) -> None:
        request.settimeout(self.request_timeout_seconds)
        with self._condition:
            self._active_requests += 1
            self._active_sockets.add(request)
            self.metrics.begin_request()
        try:
            super().process_request_thread(request, client_address)
        finally:
            with self._condition:
                self._active_requests -= 1
                self._active_sockets.discard(request)
                self.metrics.end_request()
                self._condition.notify_all()
            self._admission.release()

    def shutdown_gracefully(self, timeout_seconds: float = 10.0) -> bool:
        """Stop accepting, wait up to the deadline, then close active sockets.

        Returns True when all admitted requests completed before the deadline.
        Call from a thread other than the one running serve_forever().
        """
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            raise ValueError("shutdown_timeout_must_be_finite_and_non_negative")
        self.begin_draining()
        self.metrics.shutdown()
        if not self._serve_started.is_set():
            with self._condition:
                self._stopped = True
            self._serve_stopped.set()
            self.server_close()
            return True
        if threading.current_thread() is getattr(self, "_serve_thread", None):
            raise RuntimeError("shutdown_must_run_outside_serve_forever_thread")

        self.shutdown()
        deadline = time.monotonic() + float(timeout_seconds)
        with self._condition:
            while self._active_requests:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            drained = self._active_requests == 0
            sockets = tuple(self._active_sockets) if not drained else ()
        if not drained:
            for active_socket in sockets:
                try:
                    active_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    active_socket.close()
                except OSError:
                    pass
        self.server_close()
        return drained


def create_operational_server(
    service_host,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    max_concurrency: int = 32,
    max_request_body_bytes: int = 1_048_576,
    request_timeout_seconds: float = 10.0,
    allow_non_loopback: bool = False,
) -> OperationalHTTPServer:
    """Create the production ingress; non-loopback binding requires explicit opt-in."""
    if host not in {"127.0.0.1", "localhost"} and not allow_non_loopback:
        raise ValueError("operational_http_host_must_be_loopback")
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("invalid_http_port")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args) -> None:
            return

        def _send(
            self,
            status: int,
            payload: dict[str, Any] | None,
            *,
            request_id: str,
            content_type: str = "application/json",
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            encoded = b"" if payload is None else _json_bytes(payload)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.send_header("X-Request-ID", request_id)
            for key, value in (extra_headers or {}).items():
                if (
                    isinstance(key, str)
                    and _HEADER_NAME.fullmatch(key)
                    and isinstance(value, str)
                    and "\r" not in value
                    and "\n" not in value
                ):
                    self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD" and encoded:
                try:
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    pass
            self.close_connection = True

        def _request_headers(self) -> dict[str, str] | None:
            result: dict[str, str] = {}
            for key, value in self.headers.items():
                normalized = key.lower()
                if normalized in result:
                    return None
                result[normalized] = value
            return result

        def _read_body(self, headers: dict[str, str]) -> tuple[int, dict[str, Any] | None]:
            if "transfer-encoding" in headers:
                return 400, None
            if self.command not in {"POST", "PUT", "PATCH"}:
                raw_length = headers.get("content-length", "0")
                return (400, None) if raw_length not in {"0", ""} else (0, {})
            raw_length = headers.get("content-length")
            if raw_length is None:
                return 411, None
            if not raw_length.isascii() or not raw_length.isdecimal():
                return 400, None
            if len(raw_length) > 10:
                return 413, None
            length = int(raw_length)
            if length > self.server.max_request_body_bytes:
                return 413, None
            if length and headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                return 415, None
            try:
                raw = self.rfile.read(length)
            except socket.timeout:
                return 408, None
            if len(raw) != length:
                return 400, None
            try:
                body = json.loads(
                    raw or b"{}",
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_non_finite,
                )
                if not isinstance(body, dict):
                    return 400, None
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                return 400, None
            return 0, body

        def _dispatch(self, method: str) -> None:
            started = time.monotonic()
            request_id = str(uuid.uuid4())
            status = 500
            try:
                parsed = urlsplit(self.path)
                path = parsed.path
                if method in {"GET", "HEAD"} and path == "/health/live":
                    status = 200 if self.server.live else 503
                    self._send(status, {"status": "live" if status == 200 else "stopped"}, request_id=request_id)
                    return
                if method in {"GET", "HEAD"} and path == "/health/ready":
                    status = 200 if self.server.ready else 503
                    self._send(status, {"status": "ready" if status == 200 else "not_ready"}, request_id=request_id)
                    return
                if method in {"GET", "HEAD"} and path == "/metrics":
                    status = 200
                    self._send(
                        status,
                        None,
                        request_id=request_id,
                        content_type="text/plain; version=0.0.4; charset=utf-8",
                    )
                    # Replace the empty response body with the current metrics exposition.
                    metrics = self.server.metrics.render(ready=self.server.ready).encode("utf-8")
                    self.send_response  # keep the response writer owned by this handler
                    return

                headers = self._request_headers()
                if headers is None:
                    status = 400
                    self._send(status, {"error": {"code": "INVALID_HEADERS"}}, request_id=request_id)
                    return
                if "transfer-encoding" in headers:
                    status = 400
                    self._send(status, {"error": {"code": "TRANSFER_ENCODING_UNSUPPORTED"}}, request_id=request_id)
                    return
                body_status, body = self._read_body(headers)
                if body_status:
                    code = {
                        400: "INVALID_REQUEST_BODY",
                        408: "REQUEST_TIMEOUT",
                        411: "CONTENT_LENGTH_REQUIRED",
                        413: "BODY_TOO_LARGE",
                        415: "UNSUPPORTED_MEDIA_TYPE",
                    }.get(body_status, "INVALID_REQUEST_BODY")
                    status = body_status
                    self._send(status, {"error": {"code": code}}, request_id=request_id)
                    return

                segments = path.split("/")
                if len(segments) < 2 or not segments[1]:
                    status = 404
                    self._send(status, {"error": {"code": "SERVICE_NOT_FOUND"}}, request_id=request_id)
                    return
                service_id = unquote(segments[1])
                if not _SERVICE_ID.fullmatch(service_id):
                    status = 404
                    self._send(status, {"error": {"code": "SERVICE_NOT_FOUND"}}, request_id=request_id)
                    return
                target = "/" + "/".join(segments[2:])
                if parsed.query:
                    target += "?" + parsed.query
                response: RuntimeResponse = self.server.service_host.dispatch_authenticated(
                    service_id,
                    method,
                    target,
                    body or {},
                    authorization=headers.get("authorization"),
                    headers=headers,
                    request_id=request_id,
                )
                status = response.status_code
                if type(status) is not int or not 100 <= status <= 599 or not isinstance(response.body, dict):
                    status = 502
                    self._send(status, {"error": {"code": "INVALID_UPSTREAM_RESPONSE"}}, request_id=request_id)
                    return
                self._send(
                    status,
                    None if status == 204 else response.body,
                    request_id=request_id,
                    extra_headers=response.headers,
                )
            except socket.timeout:
                status = 408
                try:
                    self._send(status, {"error": {"code": "REQUEST_TIMEOUT"}}, request_id=request_id)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            except (BrokenPipeError, ConnectionResetError, OSError):
                status = 499
            except Exception:
                status = 500
                try:
                    self._send(status, {"error": {"code": "INTERNAL_ERROR"}}, request_id=request_id)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
            finally:
                self.server.metrics.record(method, status, time.monotonic() - started)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_HEAD(self) -> None:
            self._dispatch("HEAD")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_PUT(self) -> None:
            self._dispatch("PUT")

        def do_PATCH(self) -> None:
            self._dispatch("PATCH")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def do_OPTIONS(self) -> None:
            self._dispatch("OPTIONS")

    return OperationalHTTPServer(
        (host, port),
        Handler,
        service_host=service_host,
        max_concurrency=max_concurrency,
        max_request_body_bytes=max_request_body_bytes,
        request_timeout_seconds=request_timeout_seconds,
    )
