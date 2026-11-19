# Execution handoff

## Resume protocol

1. Read AGENTS.md and this directory's README.md.
2. Run python project_control.py validate, python project_control.py status, and python scripts/check_claims.py.
3. Inspect current branch, base, open PRs, diffs, and latest workflow runs; never rely on a previous conversation's CI state.
4. Read STATE.json and continue only tasks whose dependencies and branch preconditions still hold.
5. Select the highest-priority ready task within the WIP limit. If a task is blocked, record it and continue independent work.
6. Before implementation, record the hypothesis, acceptance command, expected output, and recovery route in TASKS.json.
7. After implementation, run acceptance and regression checks, review the diff, and update TASKS.json, STATE.json, PROGRESS.json, and RUN_LEDGER.jsonl.
8. Use stacked PRs where a prerequisite PR is still open. Do not merge to main, release, deploy production, change security settings, or perform destructive external actions without explicit owner authorization.

## Current checkpoint

- Baseline: research/reboot-core at 23f9c77d8ce9a8d55895c6c4903a4ff409ba5781.
- PR #64: feat/project-control-plane -> research/reboot-core; open, ready for review.
- PR #65: ci/unified-workflow -> feat/project-control-plane; run 44428892897 passed Layer 0 and Layer 1 after the shared-runner threshold correction. The always-on E-009 smoke validates product-path expectations only; the manual ten-run job retains the capacity gate. A fresh run after the latest evidence-ledger updates is in progress.
- PR #66 and #67: superseded drafts; their branches were based on older PR #65 heads. Do not merge them.
- Working branch: feat/evidence-claims-gates-v3, based on the latest PR #65 head.
- Current milestone: C1 (execution governance and evidence integrity).
- Active tasks: CP-007 (final retarget/revalidation after PR #64), CP-005 (claims validator; final seven-claim verification pending).
- Next: finish CP-005 validator and negative tests; do not treat E-009 product-path smoke as a capacity claim or CPU model diagnostics as M3 acceptance.
- Do not merge to main, alter repository security settings, run paid GPU/API workloads, or delete research branches/tags without owner authorization.
