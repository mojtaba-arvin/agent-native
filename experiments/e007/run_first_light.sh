#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OUTPUT_DIR="${FIRST_LIGHT_OUTPUT_DIR:-/tmp/agent-native-e007-first-light}"

python experiments/e007/eval_runner.py \
  --case experiments/e007/evals/e009-readonly-proposal-postfix-expanded-budget.eval.json \
  --model qwen3:8b \
  --arm upfront \
  --repetitions 1 \
  --max-input-tokens 120000 \
  --max-output-tokens 6000 \
  --max-tool-calls 20 \
  --max-wall-seconds 3000 \
  --num-ctx 16384 \
  --num-predict 2048 \
  --temperature 0 \
  --top-p 1 \
  --seed 42 \
  --output-dir "$OUTPUT_DIR"
