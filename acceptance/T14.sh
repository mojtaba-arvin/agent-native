#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

required = {
    "production operational HTTP server": Path("src/agent_native/operations.py"),
    "operational HTTP tests": Path("tests/test_operational_http.py"),
    "public package exports": Path("src/agent_native/__init__.py"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T14 acceptance: missing health/metrics/limits/shutdown outputs:")
    for label in missing:
        print(f"- {label}")
    sys.exit(1)

server = required["production operational HTTP server"].read_text(encoding="utf-8")
tests = required["operational HTTP tests"].read_text(encoding="utf-8")
exports = required["public package exports"].read_text(encoding="utf-8")

checks = {
    "bounded operational HTTP server and factory": "class OperationalHTTPServer" in server and "def create_operational_server(" in server,
    "liveness and readiness endpoints": all(marker in server for marker in ("/health/live", "/health/ready")),
    "Prometheus operational metrics endpoint": "/metrics" in server and "http_requests_total" in server,
    "bounded concurrency and request body": all(marker in server for marker in ("max_concurrency", "max_request_body_bytes", "OVERLOADED", "BODY_TOO_LARGE")),
    "request read timeout and graceful drain": "request_timeout_seconds" in server and "shutdown_gracefully" in server,
    "package exports operational server": "OperationalHTTPServer" in exports and "create_operational_server" in exports,
    "live HTTP tests exercise lifecycle and failure contracts": all(marker in tests for marker in (
        "test_health_and_readiness_change_during_shutdown",
        "test_metrics_count_requests_and_expose_inflight",
        "test_body_limit_rejects_before_dispatch",
        "test_concurrency_limit_returns_503",
        "test_graceful_shutdown_drains_inflight_request",
    )),
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T14 acceptance: operational contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T14 acceptance: operational HTTP health, metrics, bounded admission/body handling, timeout, and graceful-drain contracts are present.")
PY

PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest tests.test_operational_http -v
