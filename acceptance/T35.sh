#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m unittest tests.test_authentication -v
python3 scripts/mutation_security.py
