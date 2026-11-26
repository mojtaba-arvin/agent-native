"""Two-process HTTP receiver used to exercise E-011 failure semantics.

This is a local conformance fixture, not a production RPC server or auth system.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def initialize(path: str) -> None:
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS receiver_effects (
                tenant_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                PRIMARY KEY (tenant_id, operation, idempotency_key)
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def effect_count(path: str) -> int:
    connection = sqlite3.connect(path, timeout=10)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM receiver_effects").fetchone()[0])
    finally:
        connection.close()


class _Handler(BaseHTTPRequestHandler):
    server_version = "E011Receiver/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _respond(self, status: int, payload: dict) -> None:
        body = _canonical(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/invoke":
            self._respond(404, {"error": "not_found"})
            return
        principal = self.headers.get("X-Principal", "")
        tenant = self.headers.get("X-Tenant", "")
        capability = self.headers.get("X-Capability", "")
        key = self.headers.get("Idempotency-Key", "")
        if not principal.strip() or not tenant.strip() or capability != "ledger.write":
            self._respond(403, {"error": "capability_denied"})
            return
        if not key.strip():
            self._respond(400, {"error": "idempotency_key_required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, {"error": "invalid_content_length"})
            return
        if length <= 0 or length > 65536:
            self._respond(413, {"error": "body_size_invalid"})
            return
        try:
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or set(request) != {"tenant_id", "operation", "payload"}:
                raise ValueError("invalid_request_shape")
            if request["tenant_id"] != tenant:
                self._respond(403, {"error": "tenant_mismatch"})
                return
            operation = request["operation"]
            payload = request["payload"]
            if not isinstance(operation, str) or not operation.strip() or not isinstance(payload, dict):
                raise ValueError("invalid_operation_or_payload")
            payload_hash = _digest(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            self._respond(400, {"error": "invalid_request"})
            return

        connection = sqlite3.connect(self.server.db_path, timeout=10, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """SELECT payload_hash, result_json FROM receiver_effects
                   WHERE tenant_id=? AND operation=? AND idempotency_key=?""",
                (tenant, operation, key),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                if existing[0] != payload_hash:
                    self._respond(409, {"error": "idempotency_payload_conflict"})
                else:
                    self._respond(200, {**json.loads(existing[1]), "replayed": True})
                return

            effect_id = _digest({"tenant": tenant, "operation": operation, "key": key})
            result = {
                "accepted": True,
                "effect_id": effect_id,
                "payload_hash": payload_hash,
                "replayed": False,
            }
            connection.execute(
                """INSERT INTO receiver_effects
                   (tenant_id, operation, idempotency_key, payload_hash, result_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (tenant, operation, key, payload_hash, _canonical(result)),
            )
            if self.headers.get("X-Test-Fail-Before-Commit") == "1":
                connection.rollback()
                self._respond(503, {"error": "injected_precommit_failure"})
                return
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            self._respond(503, {"error": "receiver_storage_failure"})
            return
        finally:
            connection.close()

        # Simulates a process dying after durable commit but before response.
        if self.headers.get("X-Test-Crash-After-Commit") == "1":
            os._exit(71)
        self._respond(200, result)


class _Receiver(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, db_path: str):
        self.db_path = db_path
        super().__init__(address, handler)


def serve(db_path: str, ready: multiprocessing.Queue) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    initialize(db_path)
    server = _Receiver(("127.0.0.1", 0), _Handler, db_path)
    ready.put(server.server_address[1])
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()


def start_receiver(db_path: str):
    """Start a separate receiver process and return (process, base_url)."""
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    process = context.Process(target=serve, args=(str(db_path), ready), daemon=True)
    process.start()
    try:
        port = ready.get(timeout=10)
    except Exception:
        process.terminate()
        process.join(timeout=5)
        raise RuntimeError("receiver_startup_failed")
    return process, f"http://127.0.0.1:{port}"


def invoke(base_url: str, *, tenant: str, operation: str, key: str, payload: dict,
           principal: str = "service-a", capability: str = "ledger.write",
           crash_after_commit: bool = False, fail_before_commit: bool = False):
    """Perform one invocation; return (status, decoded response). Transport loss raises."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    body = _canonical({
        "tenant_id": tenant,
        "operation": operation,
        "payload": payload,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Principal": principal,
        "X-Tenant": tenant,
        "X-Capability": capability,
        "Idempotency-Key": key,
    }
    if crash_after_commit:
        headers["X-Test-Crash-After-Commit"] = "1"
    if fail_before_commit:
        headers["X-Test-Fail-Before-Commit"] = "1"
    request = Request(f"{base_url}/invoke", data=body, headers=headers, method="POST")
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())
