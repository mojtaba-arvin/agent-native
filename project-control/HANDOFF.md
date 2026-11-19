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
- CP-009 dependency-aware scheduling/recovery is complete through PR #84.
- M2-001 ServiceRegistry, M2-002 generic declarative CRUD/list/job/event dispatch, M2-003 Service-independent Gateway, and M2-004 multi-service proof are integrated. M2 is complete on `research/reboot-core@0e8e8fe67f410add6d851584eeb7434f2f707aa8`.
- PR #81 passed Layer 0 and Layer 1 on head `0e53539ac8652a79bd831c4883ec9ff26ebf411c`; it was integrated under the repository owner's exact-head waiver. The waiver is not peer review. PR #82 passed Layer 0 and Layer 1 on head `1607feafeea17b3d7dfcd1e51f8a3ec5544731ec` and was integrated. The integrated merge commit also passed push CI run #44491048454.
- PR #90 added the narrow owner-waiver CI path; the two-human-review policy remains the default. C3 remains pending until genuine independent peer reviews are obtained.
- PR #89 hardened E-007 evaluator filesystem-custody preflight: symlink and hard-link rejection, owner/mode checks, and no oracle path in the public evidence object. These checks are not OS/container/network isolation.
- M3 is now the current milestone. M3-000 topology smoke is complete. M3-001 remains blocked because no qualifying free/open-weight model cohort or protected hidden-oracle custody path has been demonstrated. The owner authorized zero paid spend, limited to GitHub Actions free usage for this public repository. No paid API/GPU call or oracle cohort has been run.
- The manual Qwen3 CPU workflow remains exploratory only and cannot satisfy M3 acceptance. The cohort remains draft and non-executable.
- BLK-001 (main branch protection/integration authority), BLK-004 (qualifying zero-cost model and protected hidden-oracle path), and BLK-007 (C3 peer review) remain open; BLK-007 does not block M3 preparation.
- No main merge, production deployment, paid provider call, paid GPU evaluation, or destructive branch operation has been performed.

## Next actions

1. M3-000 is complete. PR #93 integrated runtime probes and post-merge topology run #44494715332 passed on `research/reboot-core@ec3975ff11f33516e0d98e349283cbf7b3f19789`. Both separate jobs reported UID 1001, read-only root, noexec /tmp, NoNewPrivs, zero CapEff, blocked outbound networking, 2 GiB memory, 1 CPU, and 64 PIDs. The agent artifact contained only candidate/trace; the evaluator artifact contained only score.json. The smoke used a deterministic stub and synthetic oracle only. The current preflight checks are defense-in-depth only and do not establish process, filesystem, or network isolation.
2. Investigate and pin a free-tier model cohort that can meet the preregistered quality requirements. Keep CPU-only Qwen3 diagnostics exploratory; if no free path is decision-grade, preserve the blocker rather than lowering acceptance.
3. Keep the M3 cohort non-executable until hidden-oracle custody, sandbox separation, model identity, task fixtures, and preregistration hashes are verified.
4. Pursue genuine independent human reviews for C3 in parallel; do not represent the owner waiver as peer review.
5. Do not merge to `main`, deploy production, or incur paid API/GPU spend.
