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

- PR #70 (M1) is merged. C0, C1, M0, and M1 are complete with evidence-backed claims.
- PR #77 carries M2-001: manifest-backed ServiceRegistry, Catalog and Inventory manifests, trusted handler references, default-deny policy validation, and path/symlink rejection. Its Layer 0 and Layer 1 run #44450365382 passed 15/15 suites and 646 known tests.
- M2-001 is complete. M2-002 generic declarative CRUD/job/event dispatch is active on `feat/m2-declarative-handlers`.
- M3 has two tracked tasks and three public task prompts. The cohort remains unregistered and non-executable. An evaluator-boundary scaffold now rejects oracle files inside the agent workspace, symlinks, and weak file permissions; actual process isolation remains unimplemented until owner setup.
- Owner gates remain BLK-001 (main-branch merge/security authority) and BLK-004 (M3 approved spend/provider/runner).
- No merge to `main`, production deployment, provider call, paid model/GPU evaluation, or destructive branch operation has been performed.

## Next actions

1. Implement generic CRUD/job/event handlers using explicit host-registered handler IDs and adapters.
2. Bind handlers to manifest specs without dynamic imports or service-specific core branches.
3. Enforce tenant identity from trusted request context and default-deny effect/capability checks.
4. Run the installed-package and full deterministic CI matrix before integrating M2-002.
