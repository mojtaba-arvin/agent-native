#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import re
import sys
import tomllib

required = {
    "production PostgreSQL server composition": Path("src/agent_native/server.py"),
    "T18 disposable PostgreSQL deployment": Path("experiments/t18/compose.yaml"),
    "T18 reproducible pilot runner": Path("experiments/t18/run-pilot.sh"),
    "T18 black-box pilot checks": Path("experiments/t18/test_pilot.py"),
    "T18 deployment and findings runbook": Path("experiments/t18/README.md"),
}
missing = [label for label, path in required.items() if not path.is_file()]
if missing:
    print("T18 acceptance: PostgreSQL container pilot is not implemented:")
    for label in missing:
        print(f"- missing {label}: {required[label]}")
    sys.exit(1)

cli = Path("src/agent_native/cli.py").read_text(encoding="utf-8")
server = required["production PostgreSQL server composition"].read_text(encoding="utf-8")
dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
compose = required["T18 disposable PostgreSQL deployment"].read_text(encoding="utf-8")
runner = required["T18 reproducible pilot runner"].read_text(encoding="utf-8")
tests = required["T18 black-box pilot checks"].read_text(encoding="utf-8")
pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
dependencies = pyproject.get("project", {}).get("dependencies", [])

checks = {
    "production CLI exposes an explicit serve command": "def command_serve(" in cli and 'add_parser("serve"' in cli,
    "server composes PostgreSQL, trusted handlers, authentication, and bounded HTTP ingress": all(
        marker in server for marker in (
            "PostgresResourceRepository", "ServiceHost", "CapabilityTokenAuthority",
            "built_in_handler_registry", "create_operational_server",
        )
    ),
    "PostgreSQL driver is a declared runtime dependency": any(
        isinstance(item, str) and item.lower().startswith("psycopg")
        for item in dependencies
    ),
    "T15 image retains its explicit CLI entrypoint and non-root user": (
        'ENTRYPOINT ["agent-native"]' in dockerfile and "USER 65532:65532" in dockerfile
    ),
    "compose uses the T15 image and an immutable PostgreSQL image": (
        "agent-native:t15" in compose and re.search(r"postgres:[^\s@]+@sha256:[0-9a-f]{64}", compose) is not None
    ),
    "PostgreSQL readiness gates application startup": (
        "pg_isready" in compose and "service_healthy" in compose
    ),
    "database credentials and token signing key are injected, not committed": all(
        marker in compose for marker in ("AGENT_NATIVE_POSTGRES_DSN", "AGENT_NATIVE_TOKEN_SIGNING_KEY")
    ) and "change-me" not in compose.lower(),
    "database has no published host port and app binds only to loopback": (
        "127.0.0.1:" in compose and "ports:" not in compose.split("  app:", 1)[0]
    ),
    "application uses a read-only root, non-root UID, and dropped capabilities": all(
        marker in compose for marker in ('user: "65532:65532"', "read_only: true", "cap_drop:", "no-new-privileges:true")
    ),
    "pilot runner builds the T15 image and tears down only its disposable stack": (
        "docker build" in runner and "docker compose" in runner
        and "down --volumes" in runner and "T18_EVIDENCE_DIR" in runner
    ),
    "black-box checks cover PostgreSQL persistence, auth, tenant isolation, and operational health": all(
        marker in tests for marker in (
            "test_postgres_persists_across_container_restart",
            "test_missing_and_invalid_tokens_fail_closed",
            "test_cross_tenant_resource_is_not_visible",
            "test_health_readiness_and_metrics",
            "test_create_read_and_audit_are_durable",
        )
    ),
    "pilot runbook defines deployment, evidence, and limitations": all(
        marker in required["T18 deployment and findings runbook"].read_text(encoding="utf-8")
        for marker in ("Deployment configuration", "Acceptance evidence", "Operational findings", "Limitations")
    ),
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T18 acceptance: PostgreSQL container pilot contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T18 acceptance: container/PostgreSQL pilot contract is present.")
PY

bash -n experiments/t18/run-pilot.sh
python3 -m py_compile src/agent_native/server.py experiments/t18/test_pilot.py
python3 -m unittest tests.test_server -v
python3 -m unittest discover -s experiments/t18 -p 'test_*.py' -v
T18_EVIDENCE_DIR="${T18_EVIDENCE_DIR:-${RUNNER_TEMP:-/tmp}/agent-native-t18-${GITHUB_RUN_ID:-local}}" \
  bash experiments/t18/run-pilot.sh --acceptance
