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
- M2-003 Service-independent Gateway is implemented and CI-green on feat/m2-service-independent-gateway; it remains open for two independent reviews before integration.
- M2-004 cross-service proof is prepared on feat/m2-second-service-proof, stacked on M2-003; Layer 0 and Layer 1 are green.
- CP-009 dependency-aware scheduler/recovery is active on feat/control-plane-scheduler; active workstreams and integration owners are recorded in STATE.json.
- M3 evaluator boundary scaffold is merged. It rejects workspace-local oracle files, symlinks, weak oracle permissions, and candidate-hash discontinuity. Actual process isolation remains unimplemented.
- M3 cohort remains draft, unregistered, no-apply, and non-executable. Owner setup still requires protected evaluator environment, evaluator-only oracle key, isolated runner/image digest, model identities, and approved budget.
- Owner gates remain BLK-001 (main-branch merge/security authority) and BLK-004 (M3 approved spend/provider/runner).
- No main merge, production deployment, provider call, paid model/GPU evaluation, or destructive branch operation has been performed.

## Next actions

1. Complete CP-009 scheduler tests and recovery validation.
2. Complete M2-003 independent reviews before merging; then retarget M2-004 and integrate it.
3. Keep M3 cohort non-executable until the protected evaluator environment, oracle separation, runner, model identities, and budget are verified.
4. Do not merge to main or alter repository security settings without explicit owner authorization.
