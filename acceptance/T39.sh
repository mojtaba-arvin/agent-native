#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# The negative baseline must fail on invalid indices and the old E-009 warm-up caller.

python3 -m unittest discover -s experiments/e002 -p 'test_product_workload.py' -v

python3 - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, "experiments/e002")
from product_workload import WORKLOAD_SEED, mix_counts, request_class

def must_raise(error_type, call, label):
    try:
        call()
    except error_type:
        return
    raise AssertionError(f"{label}: expected {error_type.__name__}")

must_raise(ValueError, lambda: request_class(-1), "negative request index")
must_raise(TypeError, lambda: request_class(True), "boolean request index")
must_raise(TypeError, lambda: request_class(0, seed=True), "boolean seed")
must_raise(TypeError, lambda: mix_counts(True), "boolean request count")
must_raise(ValueError, lambda: mix_counts(-1), "negative request count")

assert mix_counts(5000, seed=WORKLOAD_SEED) == {
    "authorized_read": 3000,
    "validate_plan": 1000,
    "job_admission": 500,
    "expected_denial": 500,
}

smoke = Path("experiments/e009/performance_smoke.py").read_text(encoding="utf-8")
assert "warmup_start = args.repetitions * args.requests" in smoke
assert "range(warmup_start, warmup_start + 100)" in smoke
assert "range(-100, 0)" not in smoke
print("T39 workload contract and E-009 warm-up compatibility passed")
PY
