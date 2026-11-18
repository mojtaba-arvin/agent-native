#!/usr/bin/env bash
set -euo pipefail

PINNED_REV="a972418e5795a863a1435bf69cc6592e782c6abd"
ROOT="$(git rev-parse --show-toplevel)"
WORKTREE="$(mktemp -d "${TMPDIR:-/tmp}/agent-native-second-light.XXXXXX")"
rmdir "$WORKTREE"
cleanup() {
  git -C "$ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! git -C "$ROOT" cat-file -e "${PINNED_REV}^{commit}" 2>/dev/null; then
  git -C "$ROOT" fetch --no-tags origin "$PINNED_REV"
fi

git -C "$ROOT" worktree add --detach "$WORKTREE" "$PINNED_REV" >/dev/null
ACTUAL_REV="$(git -C "$WORKTREE" rev-parse HEAD)"
if [[ "$ACTUAL_REV" != "$PINNED_REV" ]]; then
  echo "Refusing Second Light: expected $PINNED_REV, got $ACTUAL_REV" >&2
  exit 78
fi

# Commit A's per-turn measurement contract is required for a comparable repeat.
if ! grep -q 'payload_sha256' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'prompt_states_path' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'payload_metadata' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'def _build_compaction_ledger' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'def prevalidate_catalog_operation' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'def prevalidation_repair_key' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'exhausted = bool(repair_attempts)' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'INSPECTION_OPERATION_REQUIRED' "$WORKTREE/experiments/e009/agent_gateway.py" ||
   ! grep -q 'INSPECTION_PROGRESS_REPAIR_EXHAUSTED' "$WORKTREE/experiments/e009/agent_gateway.py"; then
  echo "Refusing Second Light: pinned revision $PINNED_REV is missing First Light prompt-state, compaction, payload, or operation-guard instrumentation." >&2
  exit 78
fi

if ! grep -q 'threading.Timer' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'active_socket.shutdown' "$WORKTREE/experiments/e009/local_agent.py"; then
  echo "Refusing Second Light: pinned revision $PINNED_REV does not contain the absolute provider-request deadline fix." >&2
  exit 78
fi

OUTPUT_DIR="${SECOND_LIGHT_OUTPUT_DIR:-/tmp/agent-native-e007-second-light}"
python "$WORKTREE/experiments/e007/eval_runner.py" \
  --case "$WORKTREE/experiments/e007/evals/e009-readonly-proposal-postfix-expanded-budget.eval.json" \
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
