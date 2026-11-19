# Execution handoff

## Resume protocol

1. Read `AGENTS.md` and this directory's `README.md`.
2. Run `python project_control.py validate`, `python project_control.py status`, `python project_control.py self-test`, and `python project_control.py resume`.
3. Run `python scripts/check_claims.py` and `python scripts/check_preregistrations.py`.
4. Inspect current branch, base, open PRs, diffs, and latest workflow runs. Never rely on a previous conversation's CI state.
5. Read the machine-readable resume checkpoint. Continue only active tasks whose dependencies are complete and whose branch preconditions still hold.
6. Select the highest-priority ready task within the WIP limit. If a task is blocked, record it and continue independent work.
7. Before implementation, record the hypothesis, acceptance command, expected output, and recovery route in `TASKS.json`.
8. After implementation, run acceptance and regression checks, review the diff, and update task/state/progress/evidence in the same change.
9. Use stacked PRs where a prerequisite PR is still open. Do not merge to `main`, release, deploy production, change security settings, or perform destructive external actions without explicit owner authorization.

## Current checkpoint — 2026-11-19

- Baseline: `research/reboot-core@7bfd3441c81c0af1b1cbbbc7c99a35137e18daad`.
- PRs #64, #65, #68, and #69 are merged into `research/reboot-core`.
- PR #71 (M3 preflight) and PR #72 (stateless resume) are merged.
- PR #63 is closed as superseded; its branch is preserved.
- PR #70 remains open as a draft for M1 package work on `feat/m1-package-cli`.
- CP-007 and CP-008 are complete. C0, C1, and M0 are complete with evidence-backed claims.
- M1-001 is active pending the latest strengthened CI run. The package install has passed in an isolated venv on the prior revision; the new static sys.path scanner and docs require fresh validation.
- M3 preflight is documented. M3-001 remains owner-gated for an approved provider/GPU route, spend ceiling, and credentials/runner. No paid model evaluation has been dispatched.
- Open owner gates: BLK-001 (main-branch merge/security authority) and BLK-004 (M3 execution budget/provider/runner).
- No merge to `main`, security-setting changes, secret writes, release, deployment, branch deletion, or force-push has been performed.

## Next actions

1. Complete the latest M1-001 isolated-install and package-import checks.
2. Continue M1-002 package namespace migration, then implement M1-003 unified CLI and M1-004 full regression preservation.
3. Continue M3 task-corpus and sandbox/oracle implementation without dispatching paid or GPU workloads until technical gates and owner approval are satisfied.
