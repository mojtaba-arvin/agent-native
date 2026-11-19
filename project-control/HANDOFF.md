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
- PR #65: ci/unified-workflow -> feat/project-control-plane; all configured checks passed after separating the always-on E-009 product smoke from the manual capacity gate. Retarget and re-run after PR #64 is integrated.
- PR #68: feat/evidence-claims-gates-v3 -> ci/unified-workflow; run 44430692124 passed Layer 0 and Layer 1, 14 suites, 524 unit tests, 15 claims tests, and seven evidence-backed completion claims. It remains stacked until PR #65 is integrated.
- Superseded drafts PR #66 and #67 are closed; do not merge their branches.
- Working branch: feat/evidence-claims-gates-v3.
- Current milestone: C1, with M0 audit preparation now active.
- Active tasks: CP-007 (final retarget/revalidation after PR #64), CP-003 (M0 source/evidence audit).
- Completed this iteration: CP-005 evidence-backed claims gate, validated in run 44430692124.
- Next: audit source-of-truth claims across E-001–E-011 and research branches; do not infer production readiness, runtime selection, capacity, or model acceptance.
- Do not merge to main, alter repository security settings, run paid GPU/API workloads, or delete research branches/tags without owner authorization.
