#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m py_compile \
  experiments/e002/product_workload.py \
  experiments/e009/catalog.py \
  experiments/e009/serve.py \
  experiments/e009/performance_smoke.py
python3 -m unittest discover -s experiments/e002 -p "test_product*.py" -v
