#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
PINNED_REV="${GITHUB_SHA:-$(git -C "$ROOT" rev-parse HEAD)}"
REF_NAME="${GITHUB_REF_NAME:-$(git -C "$ROOT" branch --show-current)}"
if [[ "$REF_NAME" != "research/reboot-core" ]]; then
  echo "Refusing factorial pilot: expected research/reboot-core, got $REF_NAME" >&2
  exit 78
fi

WORKTREE="$(mktemp -d "${TMPDIR:-/tmp}/agent-native-e007-factorial.XXXXXX")"
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
  echo "Refusing factorial pilot: expected $PINNED_REV, got $ACTUAL_REV" >&2
  exit 78
fi

# Validate the complete matched cohort before the first model request.
ROWS_FILE="$(mktemp "${TMPDIR:-/tmp}/agent-native-e007-cases.XXXXXX")"
python "$WORKTREE/experiments/e007/validate_factorial_dispatch.py" \
  --root "$WORKTREE" \
  --manifest "$WORKTREE/experiments/e007/dispatch.json" \
  --format tsv > "$ROWS_FILE"
mapfile -t CASE_ROWS < "$ROWS_FILE"
rm -f "$ROWS_FILE"

if ! grep -q 'proposal_mode' "$WORKTREE/experiments/e009/local_agent.py" ||
   ! grep -q 'base_disclosure' "$WORKTREE/experiments/e009/agent_gateway.py" ||
   ! grep -q 'materialize_add_operation' "$WORKTREE/experiments/e007/eval_runner.py" ||
   ! grep -q 'trusted_revision' "$WORKTREE/experiments/e007/eval_runner.py"; then
  echo "Refusing factorial pilot: pinned revision is missing proposal/disclosure runner or independent-oracle support." >&2
  exit 78
fi

OUTPUT_ROOT="${FACTORIAL_OUTPUT_DIR:-/tmp/agent-native-e007-factorial-${GITHUB_RUN_ID:-local}}"
case "$OUTPUT_ROOT" in
  "$ROOT"|"$ROOT"/*) echo "Refusing output inside repository: $OUTPUT_ROOT" >&2; exit 78 ;;
esac
if [[ -d "$OUTPUT_ROOT" ]] && [[ -n "$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "Refusing to overwrite existing factorial evidence directory: $OUTPUT_ROOT" >&2
  exit 78
fi
mkdir -p "$OUTPUT_ROOT"
cp "$WORKTREE/experiments/e007/dispatch.json" "$OUTPUT_ROOT/dispatch.json"
printf 'pinned_revision=%s\n' "$ACTUAL_REV" > "$OUTPUT_ROOT/pilot-provenance.txt"
printf 'case_path\teval_id\tproposal_mode\tbase_disclosure\texit_code\n' > "$OUTPUT_ROOT/cell-results.tsv"

failures=0
cohort_abort=""
for ((index=0; index<${#CASE_ROWS[@]}; index++)); do
  row="${CASE_ROWS[$index]}"
  IFS=$'\\t' read -r CASE_PATH EVAL_ID PROPOSAL_MODE BASE_DISCLOSURE ARM REPETITIONS TEMPERATURE TOP_P SEED NUM_CTX NUM_PREDICT MAX_INPUT MAX_OUTPUT MAX_TOOLS MAX_WALL <<< "$row"
  echo "Running $EVAL_ID ($PROPOSAL_MODE / $BASE_DISCLOSURE)"
  set +e
  python "$WORKTREE/experiments/e007/eval_runner.py" \\
    --case "$WORKTREE/$CASE_PATH" \\
    --model qwen3:8b \\
    --arm "$ARM" \\
    --repetitions "$REPETITIONS" \\
    --max-input-tokens "$MAX_INPUT" \\
    --max-output-tokens "$MAX_OUTPUT" \\
    --max-tool-calls "$MAX_TOOLS" \\
    --max-wall-seconds "$MAX_WALL" \\
    --num-ctx "$NUM_CTX" \\
    --num-predict "$NUM_PREDICT" \\
    --temperature "$TEMPERATURE" \\
    --top-p "$TOP_P" \\
    --seed "$SEED" \\
    --output-dir "$OUTPUT_ROOT/$EVAL_ID"
  EXIT_CODE=$?
  set -e
  printf '%s\\t%s\\t%s\\t%s\\t%s\\n' "$CASE_PATH" "$EVAL_ID" "$PROPOSAL_MODE" "$BASE_DISCLOSURE" "$EXIT_CODE" >> "$OUTPUT_ROOT/cell-results.tsv"
  if [[ "$EXIT_CODE" -ne 0 ]]; then failures=$((failures + 1)); fi

  # Keep the matched cohort complete after an agent/task failure. Abort only
  # when shared infrastructure is broken or the result artifact is unusable.
  RESULT_FILE="$(find "$OUTPUT_ROOT/$EVAL_ID" -type f -name result.json -print | sort | tail -n 1)"
  if [[ -z "$RESULT_FILE" ]]; then
    cohort_abort="result_artifact_missing"
  else
    set +e
    GUARD_OUTPUT="$(python "$WORKTREE/experiments/e007/pilot_guard.py" "$RESULT_FILE" 2>&1)"
    GUARD_EXIT=$?
    set -e
    if [[ "$GUARD_EXIT" -ne 0 ]]; then cohort_abort="$GUARD_OUTPUT"; fi
  fi
  if [[ -n "$cohort_abort" ]]; then
    printf 'abort_reason=%s\\nabort_after_cell=%s\\n' "$cohort_abort" "$EVAL_ID" > "$OUTPUT_ROOT/cohort-abort.txt"
    echo "Stopping matched cohort before further model calls: $cohort_abort" >&2
    for ((remaining=index+1; remaining<${#CASE_ROWS[@]}; remaining++)); do
      IFS=$'\\t' read -r SKIP_PATH SKIP_ID SKIP_MODE SKIP_DISCLOSURE _ <<< "${CASE_ROWS[$remaining]}"
      printf '%s\\t%s\\t%s\\t%s\\tnot_started_infrastructure_abort\\n' "$SKIP_PATH" "$SKIP_ID" "$SKIP_MODE" "$SKIP_DISCLOSURE" >> "$OUTPUT_ROOT/cell-results.tsv"
    done
    exit 2
  fi
done

if [[ "$failures" -ne 0 ]]; then
  echo "$failures factorial cell(s) did not meet the required acceptance gate; all cells were retained for analysis." >&2
  exit 1
fi
echo "All four factorial cells completed and met the configured acceptance gate."
