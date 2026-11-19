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
- PR #65: ci/unified-workflow -> feat/project-control-plane; all configured Layer 0 and Layer 1 checks passed on its PR head in run 44424340406. It must remain stacked until PR #64 is integrated, then be retargeted to research/reboot-core and re-run.
- Working branch: feat/evidence-claims-gates, stacked on the verified PR #65 head.
- Current milestone: C1 (execution governance and evidence integrity).
- Active tasks: CP-007 (final base-branch integration check), CP-005 (evidence ledger and claims enforcement).
- Next: finish CP-005 validator and negative tests; do not treat E-009 product-path smoke as a capacity claim or CPU model diagnostics as M3 acceptance.
- Do not merge to main, alter repository security settings, run paid GPU/API workloads, or delete research branches/tags without owner authorization.
