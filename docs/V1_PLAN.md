# V1 Plan (rules only)

Goal: one production-usable service on PostgreSQL: CRUD, list, jobs, capability tokens, single node. Out of scope until v0.1 ships: multi-node, E-011, WASI, BEAM, host-language handlers, auto-apply in production.

This file holds rules only. It holds no status, no task table and no progress notes.

## 1. Single sources of truth

| What | Where | Never |
|---|---|---|
| Task list, status, dependencies, attempts | GitHub Issues with label `v1`, title `[Txx] ...` | in any file |
| Rules | this file, read from the base branch | from your own branch |
| Done-ness of a task | `acceptance/Txx.sh` passes on the merged head | by someone's claim |
| Enforcement | `task-gate` and `task-acceptance` workflows on the base branch | by agent discipline alone |

Read the rules from any branch with:

```bash
git fetch origin research/reboot-core
git show origin/research/reboot-core:docs/V1_PLAN.md
```

A branch that lacks this file is not an excuse. Merge `origin/research/reboot-core` into it, or read the file as above.

## 2. Resume protocol (no plan needs to be re-given)

Open the issue list with label `v1` and state open (via the host's issue browser or API; `gh` is not required).

Pick the lowest-numbered open task whose `Depends:` tasks are all closed and that is not labeled `blocked`. Parallel agents: claim by assigning yourself and commenting "claimed" first. If it is already assigned to someone else, pick the next one.

Open the issue; read Outputs, Acceptance script and Recovery.

Work on a branch `task/Txx-short-name` created from `origin/research/reboot-core`.

## 3. Task contract

Every issue has: Outputs, a `Depends:` line, an `Attempt budget:` line (default 3), Recovery, and exactly one label `kind:code|docs|decision|research|process`.

Every product, documentation, decision, or research task has an `acceptance/Txx.sh` script. A `kind:process` task limited to workflow or task-gate maintenance may omit that script only when the PR adds or updates automated tests for the changed enforcement behavior. Such process PRs still require `Task: Txx`, an open v1 issue, closed dependencies, and a passing task gate.

Order per task, always in separate PRs when an acceptance script is required:

**PR A:** only `acceptance/Txx.sh`. It must fail meaningfully on the current base and explain the missing behavior. The required `acceptance` status check passes PR A only when that expected failure is observed; if the script passes on the unchanged base, PR A fails. Merge PR A.

**PR B:** the implementation. PR body starts with `Task: Txx`. The acceptance script must pass in CI.

A task closes when PR B merges. Close the issue with `Closes #N` in the PR body.

## 4. Measuring progress

Progress is computed, never written:

- Tasks: closed issues with label `v1` / total issues with label `v1` (query the host's issue list).
- Product proof: the nightly acceptance run on the base branch (T19), listing which `acceptance/*.sh` pass.
- Process health: ratio of docs and state files in the last 50 merged commits, computed by T19.

Do not write status tables, handoff notes, progress logs or summaries into the repository. Put findings in the issue comment or the PR body.

## 5. Anti-bureaucracy rules (enforced by task-gate)

No docs-only PR for a `kind:code` task. A code task must change product or test files.

`project-control/` is frozen legacy. Only `kind:decision` PRs may append to `DECISION_EVENTS.jsonl`.

An acceptance PR may touch only `acceptance/Txx*`.

An implementation PR is rejected if `acceptance/Txx.sh` is not already on the base branch.

If docs and state files exceed 10% of the last 50 merged commits, variable `NEW_WORK_PAUSED=true` is set. Then only `kind:process` PRs merge until the ratio falls.

## 6. Not getting stuck

Attempt budget: each closed-without-merge PR for a task counts as one attempt. At the budget, label the issue `blocked`, comment with what failed, and move to the next unblocked task. Do not retry the same approach.

A failing acceptance script that is itself wrong is fixed by a new acceptance PR (kind unchanged), explained in the issue.

Never wait for human approval for anything inside the v0.1 scope. Pick the reasonable option, record it in the issue, continue. Stop only for irreversible actions outside scope (spending money, publishing a release).

Runtime rule (T02/T10): pass all hard gates, p99 and CPU within the envelope, choose Rust unless Go is clearly better in dev speed and build time. If a failure-contract test fails, fix the contract before switching language.

## 7. Parallel branches

Every PR targets `research/reboot-core`. The gate runs from the target branch, so source branches need not contain any of these files.

Long-lived feature branches must merge the base at least before opening a PR.

Two agents never work on the same task: the assignee owns it.

## 8. Maintenance

Adding a task: open an issue from the template. Changing the rules: a `kind:process` PR editing this file, with a note in the issue that explains why.

A `kind:process` PR that changes only `docs/V1_PLAN.md` is permitted as the exact one-file rules-maintenance exception. Any additional path must satisfy the normal `kind:process` CI/test requirements. Workflow/gate-maintenance process tasks may omit a task acceptance script only when they add or update automated tests for the behavior they change.

A gate false positive: fix `scripts/task_gate.py` plus a new unit test in a `kind:process` PR. Never bypass the gate by editing the workflow to skip it.

## 9. Definition of done for v1

T01 to T19 closed, the nightly acceptance run green for 7 consecutive days on the base branch, and the pilot (T18) running the container image from T15 against PostgreSQL.
