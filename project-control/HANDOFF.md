# Execution handoff

## Resume protocol

1. Read `AGENTS.md` and this directory's `README.md`.
2. Run `python project_control.py validate`, `python project_control.py status`, `python project_control.py self-test`, and `python project_control.py resume`.
3. Run `python scripts/check_claims.py` and `python scripts/check_preregistrations.py`.
4. Inspect current branch, base, open PRs, diffs, and latest workflow runs. Never rely on a previous conversation's CI state.
5. Read the machine-readable resume checkpoint. Continue only tasks marked active whose dependencies are complete and whose branch preconditions still hold.
6. Select the highest-priority ready task within the WIP limit. If a task is blocked, record it and continue independent work.
7. Before implementation, record the hypothesis, acceptance command, expected output, and recovery route in `TASKS.json`.
8. After implementation, run acceptance and regression checks, review the diff, and update task/state/progress/evidence in the same change.
9. Use stacked PRs where a prerequisite PR is still open. Do not merge to `main`, release, deploy production, change security settings, or perform destructive external actions without explicit owner authorization.

## Current checkpoint — 2026-11-19

- Baseline: `research/reboot-core@10ae594f405519344b1d654e9577bd78cb1f4985`.
- PR #64: merged into `research/reboot-core` (control-plane foundation).
- PR #65: merged into `research/reboot-core` (unified layered CI); fresh post-retarget run #44429525898 passed Layer 0 and Layer 1.
- PR #68: merged into `research/reboot-core` (preregistration and append-only evidence integrity).
- PR #69: merged into `research/reboot-core` (source-pinned CI summaries and scorecards).
- PR #63: closed as superseded; its branch is preserved.
- PR #70: open draft; M1 package and runtime API work on `feat/m1-package-cli`.
- PR #71: open; M3 decision-grade evaluation preflight on `research/m3-preflight`.
- Active tasks: CP-008 (clean handoff/resume proof) and M1-001 (installable package), each on its own branch.
- CP-007 is complete. BLK-003 and BLK-006 are resolved.
- M0 remains blocked by the remaining C0/C1 exit criteria, not by pending PR integration.
- M3-001 remains owner-gated for approved provider/GPU execution budget and credentials/runner. No paid model evaluation has been dispatched.
- No merge to `main`, security-setting changes, secret writes, release, deployment, branch deletion, or force-push has been performed.

## Next actions

1. Complete CP-008 and verify `project_control.py resume` from a fresh process.
2. Finish M1-001 install/runtime package checks, then proceed to M1-002 import migration and M1-003 unified CLI.
3. Continue M3 preflight engineering without dispatching paid or GPU workloads until the isolation, cohort, and owner-approval gates are satisfied.
