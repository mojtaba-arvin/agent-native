#!/usr/bin/env bash
set -euo pipefail

python -m unittest discover -s experiments/e007 -p 'test*.py' -v
python -m json.tool experiments/e007/trace.schema.json >/dev/null
