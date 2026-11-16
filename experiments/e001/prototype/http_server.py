from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from runtime import ReferenceRuntime, RuntimeFault
from security_model import RequestContext


class StaticIdentityProvider:
    """Test-only trusted identity source; never use client-supplied claims as grants."""

    def __init__(self, tokens: dict[str, RequestContext]):
        self.tokens = dict(tokens)

    def authenticate(self, authorization: str | None) -> RequestContext | None:
        if not authorization or not authorization.startswith("Bearer "):
            return None
        return self.tokens.get(authorization.removeprefix("Bearer ").strip())


def create_server(
    runtime: ReferenceRuntime,
    identity_provider: StaticIdentityProvider,
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args) -> None:
            return

        def _send(self, status: int, payload: dict) -> None:
            encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

        def _dispatch(self, method: str) -> None:
            context = identity_provider.authenticate(self.headers.get("Authorization"))
            if context is None:
                self._send(401, {"error": {"code": "UNAUTHENTICATED"}})
                return
            body = {}
            if method in {"POST", "PUT", "PATCH"}:
                try:
                    length = int(self.headers.get("content-length", "0"))
                    raw = self.rfile.read(length)
                    body = json.loads(raw or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError("JSON body must be an object")
                except (ValueError, json.JSONDecodeError):
                    self._send(400, {"error": {"code": "INVALID_JSON"}})
                    return
            try:
                result = runtime.dispatch(method, self.path, body, context, headers=dict(self.headers.items()))
                self._send(200 if method == "POST" else 200, {"data": result})
            except RuntimeFault as error:
                status = {
                    "Unauthorized": 403,
                    "InvalidInput": 400,
                    "NotFound": 404,
                    "METHOD_NOT_ALLOWED": 405,
                    "ROUTE_NOT_FOUND": 404,
                    "UNTRUSTED_EFFECT": 403,
                    "UNDECLARED_ERROR": 500,
                }.get(error.code, 500)
                self._send(status, {"error": {"code": error.code}})

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    return server
