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
mapfile -t CASE_ROWS < <(python - "$WORKTREE" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
manifest_path = root / "experiments/e007/dispatch.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
required = {
    "schema_version", "dispatch_id", "status", "model_id", "repetitions",
    "arm", "model_settings", "cases", "no_apply", "purpose",
}
if set(manifest) != required or manifest["schema_version"] != 2:
    raise SystemExit("dispatch_manifest_schema_invalid")
if manifest["status"] != "ready_for_manual_dispatch":
    raise SystemExit("dispatch_manifest_not_ready")
if manifest["no_apply"] is not True:
    raise SystemExit("dispatch_no_apply_policy_required")
if manifest["model_id"] != "qwen3:8b" or manifest["repetitions"] != 1:
    raise SystemExit("dispatch_model_or_repetition_mismatch")
if manifest["arm"] != "upfront":
    raise SystemExit("dispatch_tool_schema_arm_mismatch")

settings = manifest["model_settings"]
expected_settings = {
    "arm": "upfront", "temperature": 0, "top_p": 1, "seed": 42,
    "num_ctx": 16384, "num_predict": 2048,
    "max_input_tokens": 120000, "max_output_tokens": 6000,
    "max_tool_calls": 20, "max_wall_seconds": 3000,
}
if settings != expected_settings:
    raise SystemExit("dispatch_model_settings_changed")

expected_cells = {
    ("snapshot", "per_operation"),
    ("delta", "per_operation"),
    ("snapshot", "upfront_full"),
    ("delta", "upfront_full"),
}
cases = manifest["cases"]
if not isinstance(cases, list) or len(cases) != 4:
    raise SystemExit("dispatch_must_contain_exactly_four_factorial_cells")
seen = set()
common = None
rows = []
for item in cases:
    if not isinstance(item, dict) or set(item) != {
        "case_path", "eval_id", "proposal_mode", "base_disclosure"
    }:
        raise SystemExit("dispatch_case_entry_invalid")
    relative = pathlib.PurePosixPath(item["case_path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise SystemExit("dispatch_case_path_invalid")
    case_path = (root / pathlib.Path(*relative.parts)).resolve()
    if root not in case_path.parents or not case_path.is_file():
        raise SystemExit("dispatch_case_file_missing_or_outside_repository")
    case = json.loads(case_path.read_text(encoding="utf-8"))
    cell = (item["proposal_mode"], item["base_disclosure"])
    if cell not in expected_cells or cell in seen:
        raise SystemExit("dispatch_factorial_cell_invalid_or_duplicate")
    seen.add(cell)
    if (
        case.get("eval_id") != item["eval_id"]
        or case.get("proposal_mode") != item["proposal_mode"]
        or case.get("base_disclosure") != item["base_disclosure"]
        or case.get("model_id") != manifest["model_id"]
        or case.get("repetitions") != manifest["repetitions"]
        or case.get("model_settings") != settings
        or case.get("task_file") != (
            "experiments/e009/AGENT_TASK_DELTA.md"
            if item["proposal_mode"] == "delta"
            else "experiments/e009/AGENT_TASK.md"
        )
    ):
        raise SystemExit("dispatch_case_identity_or_settings_mismatch")
    shared = (
        case.get("task_id"), case.get("service_id"), case.get("candidate_id"),
        case.get("expected_operation"), case.get("scorers"), case.get("budget"),
    )
    if common is None:
        common = shared
    elif shared != common:
        raise SystemExit("factorial_cases_are_not_matched")
    budget = case.get("budget", {})
    if (
        budget.get("max_total_input_tokens") != settings["max_input_tokens"]
        or budget.get("max_total_output_tokens") != settings["max_output_tokens"]
        or budget.get("max_total_wall_seconds") != settings["max_wall_seconds"]
    ):
        raise SystemExit("factorial_case_budget_mismatch")
    rows.append([
        item["case_path"], item["eval_id"], item["proposal_mode"],
        item["base_disclosure"], str(settings["arm"]), str(manifest["repetitions"]),
        str(settings["temperature"]), str(settings["top_p"]), str(settings["seed"]),
        str(settings["num_ctx"]), str(settings["num_predict"]),
        str(settings["max_input_tokens"]), str(settings["max_output_tokens"]),
        str(settings["max_tool_calls"]), str(settings["max_wall_seconds"]),
    ])
if seen != expected_cells:
    raise SystemExit("factorial_cells_incomplete")
for row in rows:
    print("\t".join(row))
PY
)

OUTPUT_ROOT="${FACTORIAL_OUTPUT_DIR:-/tmp/agent-native-e007-factorial}"
case "$OUTPUT_ROOT" in
  "$ROOT"|"$ROOT"/*) echo "Refusing output inside repository: $OUTPUT_ROOT" >&2; exit 78 ;;
esac
mkdir -p "$OUTPUT_ROOT"
cp "$WORKTREE/experiments/e007/dispatch.json" "$OUTPUT_ROOT/dispatch.json"
printf 'pinned_revision=%s\n' "$ACTUAL_REV" > "$OUTPUT_ROOT/pilot-provenance.txt"
printf 'case_path\teval_id\tproposal_mode\tbase_disclosure\texit_code\n' > "$OUTPUT_ROOT/cell-results.tsv"

failures=0
for row in "${CASE_ROWS[@]}"; do
  IFS=$'\t' read -r CASE_PATH EVAL_ID PROPOSAL_MODE BASE_DISCLOSURE ARM REPETITIONS TEMPERATURE TOP_P SEED NUM_CTX NUM_PREDICT MAX_INPUT MAX_OUTPUT MAX_TOOLS MAX_WALL <<< "$row"
  echo "Running $EVAL_ID ($PROPOSAL_MODE / $BASE_DISCLOSURE)"
  set +e
  python "$WORKTREE/experiments/e007/eval_runner.py" \
    --case "$WORKTREE/$CASE_PATH" \
    --model qwen3:8b \
    --arm "$ARM" \
    --repetitions "$REPETITIONS" \
    --max-input-tokens "$MAX_INPUT" \
    --max-output-tokens "$MAX_OUTPUT" \
    --max-tool-calls "$MAX_TOOLS" \
    --max-wall-seconds "$MAX_WALL" \
    --num-ctx "$NUM_CTX" \
    --num-predict "$NUM_PREDICT" \
    --temperature "$TEMPERATURE" \
    --top-p "$TOP_P" \
    --seed "$SEED" \
    --output-dir "$OUTPUT_ROOT/$EVAL_ID"
  EXIT_CODE=$?
  set -e
  printf '%s\t%s\t%s\t%s\t%s\n' "$CASE_PATH" "$EVAL_ID" "$PROPOSAL_MODE" "$BASE_DISCLOSURE" "$EXIT_CODE" >> "$OUTPUT_ROOT/cell-results.tsv"
  if [[ "$EXIT_CODE" -ne 0 ]]; then failures=$((failures + 1)); fi
done

if [[ "$failures" -ne 0 ]]; then
  echo "$failures factorial cell(s) did not meet the required acceptance gate; all cells were retained for analysis." >&2
  exit 1
fi
echo "All four factorial cells completed and met the configured acceptance gate."
