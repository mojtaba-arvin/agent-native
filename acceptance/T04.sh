#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

suite="experiments/e009/test_http_conformance.py"
if [[ ! -f "$suite" ]]; then
  echo "T04 acceptance: missing black-box HTTP conformance suite: $suite" >&2
  exit 1
fi

PYTHONPATH="src:experiments/e009${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import sys
import unittest

loader = unittest.TestLoader()
suite = loader.discover("experiments/e009", pattern="test_http_conformance.py")
count = suite.countTestCases()
if count < 1:
    raise SystemExit("T04 acceptance: HTTP conformance discovery found zero tests.")

result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit("T04 acceptance: HTTP conformance suite failed.")
print(f"T04 acceptance: {count} black-box HTTP conformance tests passed.")
PY
