#!/usr/bin/env bash
set -euo pipefail

python -m unittest discover -s experiments/e009 -p 'test_local_agent.py' -v
