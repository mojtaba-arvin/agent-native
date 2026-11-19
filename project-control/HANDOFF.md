# Execution handoff

## Resume protocol

1. Read `AGENTS.md` and this directory's `README.md`.
2. Run `python project_control.py validate`, `python project_control.py status`, `python project_control.py self-test`, and `python project_control.py resume`.
3. Run `python scripts/check_claims.py` and `python scripts/check_preregistrations.py`.
4. Inspect current branch, base, open PRs, diffs, and latest workflow runs. Never rely on a previous conversation's CI state.
5. Continue only active tasks whose dependencies are complete and whose branch preconditions still hold.
6. Select the highest-priority ready task within the WIP limit. If a task is blocked, record it and continue independent work.
7. Before implementation, record the hypothesis, acceptance command, expected output, and recovery route in `TASKS.json`.
8. After implementation, run acceptance and regression checks, review the diff, and update task/state/progress/evidence in the same change.
9. Do not merge to `main`, release, deploy production, change security settings, or perform destructive external actions without explicit owner authorization.

## Current checkpoint — 2026-11-19

- Baseline: `research/reboot-core@9d52c773effe42a0a0161467db401ad6505e9761`.
- PRs #64, #65, #68, #69, #71, #72, #73, #74, and #75 are merged into `research/reboot-core`.
- PR #63 is closed as superseded; its branch is preserved.
- PR #70 is ready for integration after the latest base refresh. M1-001 through M1-004 passed run #44449169805: isolated package install, import-boundary scan, E-009/E-004 parity, CLI, and all 15 deterministic suites (627 known tests).
- C0, C1, and M0 are complete with evidence-backed claims. CP-007 and CP-008 are complete.
- M3 has three public draft tasks and a non-executable cohort draft. PR #76 adds CI tests that keep it unregistered until all gates are ready.
- Owner gates remain BLK-001 (main-branch merge/security authority) and BLK-004 (M3 approved spend/provider/runner).
- No merge to `main`, security-setting changes, secret writes, release, deployment, branch deletion, or force-push has been performed.

## Next actions

1. Refresh PR #70 against the latest `research/reboot-core` base and integrate M1.
2. Start M2-001: manifest-backed ServiceRegistry, strict manifest/IR validation, duplicate/unknown service rejection, and a second service fixture.
3. Continue M3 evaluator isolation and task fixtures without dispatching paid or GPU workloads until technical gates and owner approval are satisfied.
