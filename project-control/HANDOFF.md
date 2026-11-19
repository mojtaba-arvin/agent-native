# Execution handoff

## Resume protocol

1. Read AGENTS.md and this directory's README.md.
2. Run python project_control.py validate, status, self-test, and resume.
3. Run python scripts/check_claims.py and python scripts/check_preregistrations.py.
4. Inspect current branch, base, open PRs, diffs, and latest workflow runs.
5. Continue only active tasks whose dependencies are complete.
6. If blocked, record the blocker and continue independent work.
7. Record acceptance commands and recovery routes before implementation.
8. Run acceptance and regression checks before updating task/evidence state.
9. Do not merge to main, deploy, release, change security settings, or perform destructive actions without explicit owner authorization.

## Current checkpoint — 2026-11-19

- C0, C1, M0, and M1 are complete and integrated.
- M2-001 ServiceRegistry is merged; M2-002 generic declarative CRUD/list/job/event dispatch has passed 15/15 deterministic suites, 78 installed-package tests, and Layer 1 native/container/database validation (run #44453671758).
- M2-003 Service-independent Gateway is active on feat/m2-service-independent-gateway.
- M3 evaluator boundary scaffold is merged. It rejects workspace-local oracle files, symlinks, weak oracle permissions, and candidate-hash discontinuity. Actual process isolation remains unimplemented.
- M3 cohort remains draft, unregistered, no-apply, and non-executable. Owner setup still requires protected evaluator environment, evaluator-only oracle key, isolated runner/image digest, model identities, and approved budget.
- Owner gates remain BLK-001 (main-branch merge/security authority) and BLK-004 (M3 approved spend/provider/runner).
- No main merge, production deployment, provider call, paid model/GPU evaluation, or destructive branch operation has been performed.

## Next actions

1. Validate M2-003 Gateway service resolution and typed input contracts.
2. Run the read/write capability and default-deny authorization tests.
3. Verify proposal hash integrity and stale-validation rejection.
4. Keep plan generation non-executable; there is no apply method or service.apply grant.
5. After M2-003 is green, start M2-004 second-service/no-core-change integration proof.
6. Keep M3 cohort non-executable until owner gates and evaluator process isolation are verified.
