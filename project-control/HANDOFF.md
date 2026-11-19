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

- Baseline: `research/reboot-core@24c799263efdda555b3413c3ee64d4143c7883e0`.
- PRs #64, #65, #68, #69, #71, #72, and #73 are merged into `research/reboot-core`.
- PR #63 is closed as superseded; its branch is preserved.
- PR #70 is open as a draft on `feat/m1-package-cli`; M1-001 package install and M1-002 import-boundary acceptance passed in run #44447460958. M1-003 unified CLI implementation is active and awaits fresh CI.
- C0, C1, and M0 are complete with evidence-backed completion claims. CP-007 and CP-008 are complete.
- M3 task/evaluator/runner preflight is documented in `research/M3_PREFLIGHT.md`; no paid model evaluation has been dispatched.
- Owner gates remain BLK-001 (main-branch merge/security authority) and BLK-004 (M3 approved spend/provider/runner).
- No merge to `main`, security-setting changes, secret writes, release, deployment, branch deletion, or force-push has been performed.

## Next actions

1. Validate the installed CLI in a clean virtual environment: check, inspect, run dry-run, worker, audit, help, error codes, and console-script installation.
2. If green, complete M1-003 and proceed to M1-004 full regression preservation.
3. Then continue M2 service-independent Gateway and declarative handler work; M3 task-corpus and sandbox/oracle implementation can proceed in parallel without paid model dispatch.
