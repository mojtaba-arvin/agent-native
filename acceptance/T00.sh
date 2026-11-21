#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."

python3 -I -m unittest discover -s scripts -p "test_task_gate.py"

for file in \
  docs/V1_PLAN.md \
  scripts/task_gate.py \
  scripts/test_task_gate.py \
  .github/workflows/task-gate.yml \
  .github/workflows/task-acceptance.yml \
  .github/ISSUE_TEMPLATE/task.yml \
  .github/pull_request_template.md
do
  test -f "$file" || { echo "Missing $file"; exit 1; }
done

echo "T00 acceptance: OK"
