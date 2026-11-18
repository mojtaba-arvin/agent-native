# Execution handoff

## Resume protocol

1. Read `AGENTS.md` and this directory's `README.md`.
2. Run `python project_control.py validate` and `python project_control.py status`.
3. Inspect the current branch, base branch, open PRs, and working-tree diff. Never infer that a remote PR or CI run is green from an earlier conversation.
4. Read `STATE.json`; continue the active task only if its dependencies and branch preconditions still hold.
5. Select the highest-priority ready task in `TASKS.json`. If the active task is blocked, record the reason and continue with independent work.
6. Before implementation, state the falsifiable hypothesis, acceptance command, expected output, and rollback/recovery route in the task contract.
7. After implementation, run acceptance and regression checks, independently inspect the diff, add evidence references, and update `TASKS.json`, `STATE.json`, `PROGRESS.json`, and `RUN_LEDGER.jsonl` together.
8. Create or update a PR; do not merge to `main` or change repository security settings without explicit authorization.

## Current checkpoint

- Baseline: `research/reboot-core`.
- Working branch: `feat/project-control-plane`.
- Current milestone: C0.
- Active task: CP-001 (validator/status CLI).
- Next: implement validator, verify it against intentionally malformed fixture data, then inspect and port the fast CI design only after a fresh baseline inventory.
- Do not port the entirety of `research/ci-policy-staging`; cherry-pick concepts/files only after review.
- Do not delete research branches or snapshots as part of this work.
