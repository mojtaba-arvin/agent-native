# Execution handoff

## Resume protocol

1. Read AGENTS.md and this directory's README.md.
2. Run `python project_control.py validate`, `status`, `self-test`, and `resume`.
3. Run `python scripts/check_claims.py` and `python scripts/check_preregistrations.py`.
4. Inspect current branch, base, open PRs, diffs, and latest workflow runs.
5. Continue only active tasks whose dependencies are complete.
6. If blocked, record the blocker and continue independent work.
7. Record acceptance commands and recovery routes before implementation.
8. Run acceptance and regression checks before updating task/evidence state.
9. Do not merge to main, deploy, release, change security settings, or perform destructive actions without explicit owner authorization.

## Current checkpoint — 2026-11-19

- C0, C1, M0, M1, and C2 are complete and integrated into `research/reboot-core`.
- CP-009 dependency-aware scheduling/recovery is complete through PR #84. Run #44463121689 passed deterministic Layer 0 and Layer 1; task evidence, claims, and the append-only ledger pin are recorded.
- M2-001 ServiceRegistry and M2-002 generic declarative CRUD/list/job/event dispatch are integrated.
- M2-003 Service-independent Gateway is implemented on PR #81. Layer 1 passes on head 8f6ea008ef80cf0a1ef0d29ac503f5214ad5497e. The repository owner authorized an exact-head review waiver in the PR conversation; CI support is being added. This waiver is not peer review, so C3 remains pending.
- M2-004 multi-service proof is prepared on PR #82. Its current stacked head passed Layer 0 and Layer 1 in run #44464064586; it remains pending and must not be integrated ahead of PR #81.
- The active task is M2-003. Its branch, base, and integration owner are recorded in STATE.json.
- M3 real-agent/oracle evaluation is intentionally skipped for now. No oracle, provider API, paid model, or GPU evaluation has been executed. The cohort remains draft and non-executable.
- Remaining owner gates include BLK-001 (main-branch merge/security authority) and BLK-004 (decision-grade M3 provider/GPU path). BLK-007 is being handled through a narrowly scoped owner-authorized waiver for PR #81; C3's genuine peer-review criterion remains open.
- No main merge, production deployment, provider call, paid model/GPU evaluation, or destructive branch operation has been performed.

## Next actions

1. Verify the exact-head owner-waiver gate and complete a source-level security audit on PR #81. If the head changes, obtain a new exact-SHA owner authorization or two independent reviews.
2. After fresh Layer 0/Layer 1 checks pass, integrate M2-003 into `research/reboot-core`; do not claim that the waiver constitutes peer review.
3. Retarget PR #82 to `research/reboot-core`, rerun CI against the integrated Gateway, and integrate M2-004 only after all checks pass.
4. Keep M3/oracle evaluation skipped until explicitly resumed with the required owner-approved isolation and budget controls.
5. Do not merge to `main` or alter repository security settings without explicit owner authorization.
