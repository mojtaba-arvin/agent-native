#!/usr/bin/env bash
set -euo pipefail

PINNED_REV="a972418e5795a863a1435bf69cc6592e782c6abd"
ROOT="$(git rev-parse --show-toplevel)"
WORKTREE="$(mktemp -d "${TMPDIR:-/tmp}/agent-native-e010-demo.XXXXXX")"
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
  echo "Refusing E-010 demo: expected $PINNED_REV, got $ACTUAL_REV" >&2
  exit 78
fi

LOCAL_AGENT="$WORKTREE/experiments/e009/local_agent.py"
GATEWAY="$WORKTREE/experiments/e009/agent_gateway.py"
INTERFACE="$WORKTREE/experiments/e005/interface.py"
DEMO="$WORKTREE/experiments/e010/demo_apply.py"
for required in "$LOCAL_AGENT" "$GATEWAY" "$INTERFACE" "$DEMO" "$WORKTREE/experiments/e010/run_demo.py"; do
  test -f "$required" || { echo "Missing pinned E-010 source: $required" >&2; exit 78; }
done
grep -q 'allow_sandbox_apply' "$LOCAL_AGENT"
grep -q 'sandbox-apply' "$GATEWAY"
grep -q 'if self.apply_callback is None' "$INTERFACE"
grep -q 'APPLY_DISABLED' "$INTERFACE"
grep -q 'class SandboxApplyCoordinator' "$DEMO"
grep -q 'sandbox_apply_contract_not_preserved' "$DEMO"
grep -q 'sandbox_apply_change_set_mismatch' "$LOCAL_AGENT"
grep -q 'INSPECTION_PROGRESS_REPAIR_EXHAUSTED' "$GATEWAY"

OUTPUT_DIR="${E010_OUTPUT_DIR:-/tmp/agent-native-e010-runs}"
echo "E-010 pinned source revision: $ACTUAL_REV"
python "$WORKTREE/experiments/e010/run_demo.py" \
  --model qwen3:8b \
  --ollama-url http://127.0.0.1:11434 \
  --arm upfront \
  --max-input-tokens 120000 \
  --max-output-tokens 6000 \
  --max-tool-calls 20 \
  --max-wall-seconds 3000 \
  --num-ctx 16384 \
  --num-predict 2048 \
  --temperature 0 \
  --top-p 1 \
  --seed 42 \
  --results-dir "$OUTPUT_DIR"
