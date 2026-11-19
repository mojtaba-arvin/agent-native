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

- PR #70 (M1 package, import boundary, CLI, and regression preservation) is merged into `research/reboot-core`.
- C0, C1, M0, and M1 are complete with evidence-backed claims. M1 passed 15/15 deterministic suites and 627 known tests; package tests include CLI plus E-009/E-004 parity.
- PRs #64, #65, #68, #69, #71, #72, #73, #74, #75, and #76 are merged into `research/reboot-core`.
- PR #77 contains M2-001 manifest-backed ServiceRegistry work, stacked on M1 and awaiting fresh Layer 0/Layer 1 validation.
- M2-001 introduces Catalog and Inventory manifests, trusted handler-ID references, default-deny policies, and path/symlink/traversal rejection. It does not dynamically import manifest code.
- M3 has three public draft tasks and an unregistered non-executable cohort draft. CI enforces that no provider, cost, runner, or evaluator-isolation gate is silently treated as complete.
- Owner gates remain BLK-001 (main-branch merge/security authority) and BLK-004 (M3 approved spend/provider/runner).
- No merge to `main`, security-setting changes, secret writes, release, deployment, or branch deletion has been performed.

## Next actions

1. Complete M2-001 installed-package and native/container/database CI validation.
2. Implement M2-002 generic declarative handler dispatch with explicit host-registered handlers and default-deny policy checks.
3. Continue M3 evaluator isolation and immutable baseline fixtures without dispatching paid or GPU workloads until technical gates and owner approval are satisfied.
