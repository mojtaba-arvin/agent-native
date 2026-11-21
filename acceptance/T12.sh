#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

security = Path("src/agent_native/security.py")
host = Path("src/agent_native/host.py")
tests = Path("tests/test_authentication.py")
required = (security, host, tests)
missing = [str(path) for path in required if not path.is_file()]
if missing:
    print("T12 acceptance: missing authenticated capability boundary:")
    for path in missing:
        print(f"- {path}")
    sys.exit(1)

security_text = security.read_text(encoding="utf-8")
host_text = host.read_text(encoding="utf-8")
test_text = tests.read_text(encoding="utf-8")

checks = {
    "signed capability token authority": "class CapabilityTokenAuthority" in security_text,
    "HMAC-SHA256 signature verification": "hmac.compare_digest" in security_text and "sha256" in security_text,
    "strict bearer authentication entrypoint": "def authenticate(" in security_text,
    "authenticated host dispatch boundary": "def dispatch_authenticated(" in host_text,
    "missing and invalid credentials are rejected": "test_missing_authorization_is_unauthenticated" in test_text and "test_tampered_token_is_unauthenticated" in test_text,
    "expired and future tokens are rejected": "test_expired_token_is_unauthenticated" in test_text and "test_future_token_is_unauthenticated" in test_text,
    "capability, tenant and resource scopes default deny": all(marker in test_text for marker in ("test_missing_capability_is_forbidden", "test_wrong_tenant_is_forbidden", "test_resource_scope_is_enforced")),
    "valid signed capability token dispatches": "test_valid_token_dispatches" in test_text,
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    print("T12 acceptance: authentication/default-deny contract is incomplete:")
    for label in failed:
        print(f"- {label}")
    sys.exit(1)

print("T12 acceptance: signed identity, bearer verification, authenticated host boundary, and negative authorization tests are present.")
PY

PYTHONPATH="src:experiments/e009${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest tests.test_authentication -v
