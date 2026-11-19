# Project Control Plane

This directory is the versioned execution state for the Agent Native v0.1 programme. It is deliberately separate from the framework runtime and does not change the product architecture.

## Source of truth

- [VISION.md](VISION.md): outcome and scope.
- [ROADMAP.json](ROADMAP.json): milestones, dependencies, and exit criteria.
- [TASKS.json](TASKS.json): executable task contracts and current status.
- [STATE.json](STATE.json): current checkpoint and active work.
- [DECISIONS.json](DECISIONS.json): append-only decision register.
- [BLOCKERS.json](BLOCKERS.json): unresolved blockers and required authority.
- [RUN_LEDGER.jsonl](RUN_LEDGER.jsonl): append-only execution/evidence event stream.
- [PROGRESS.json](PROGRESS.json): evidence-backed milestone assessment.
- [POLICY.json](POLICY.json): autonomy, safety, retry, and integration rules.
- [HANDOFF.md](HANDOFF.md): deterministic resume instructions.
- [CI_PORT_AUDIT.md](CI_PORT_AUDIT.md): reviewed risks and safe port sequence for the staging fast-CI candidate.
- [CI_WORKFLOW_MIGRATION.md](CI_WORKFLOW_MIGRATION.md): responsibility map for the unified CI workflow.
- [M0_AUDIT.md](M0_AUDIT.md): current source/evidence audit and v0.1 gap assessment.
- [BRANCH_INVENTORY.md](BRANCH_INVENTORY.md): current branch graph and preserved unique artifacts.
- [PREREGISTRATIONS.json](PREREGISTRATIONS.json): frozen benchmark/evidence manifest registry.
- [DECISION_EVENTS.jsonl](DECISION_EVENTS.jsonl): hash-chained append-only decision, preregistration, and run-ledger integrity events.
- [E-009 capacity confirmation manifest](../experiments/e009/capacity-confirmation-v1.json): frozen ten-repetition workload and capacity thresholds consumed by the manual workflow.
- [check_claims.py](../scripts/check_claims.py): fail-closed validation for evidence-backed completion claims.
- [generate_scorecard.py](../scripts/generate_scorecard.py): derives run-bound scorecards from CI summaries, the run ledger, and the progress register.

## Validate

Run:

```sh
python project_control.py validate
python project_control.py status
python scripts/check_claims.py
python scripts/check_preregistrations.py
```

The `schedule` command emits a deterministic, read-only plan of dependency-ready work within the WIP limit. It requires explicit `execution.branch`, `execution.base_branch`, and `execution.integration_owner` metadata before selecting a task. Only `kind=task_attempt` ledger events affect retry recovery: repeated failures with the same failure signature or repeated no-progress attempts stop automatic retries and return a `replan_required` record. Scheduling never changes task status or retries work itself. To make recovery decisions durable, append task attempts to `RUN_LEDGER.jsonl` using `kind=task_attempt` and outcomes `failed`, `no_progress`, `progress`, or `completed`; `failed` requires a stable non-empty `failure_signature`. Pair every ledger append with a new hash-chained `DECISION_EVENTS.jsonl` run-ledger pin in the same commit. The preregistration checker verifies the append-only prefix and current Git blob hash. The `resume` command emits a machine-readable checkpoint containing the active task contracts, dependency readiness, WIP limit, next action, and open blockers. It refuses to resume invalid state or active tasks with incomplete dependencies. The control-plane validator checks structural invariants and cross-file references. The claims checker additionally requires verified completion claims to resolve to successful ledger events with immutable run, commit, or GitHub Actions run references, and requires every verified milestone criterion to map to exactly one such claim. The preregistration checker pins frozen manifests and decision inputs by Git blob SHA, validates the hash-chained decision events and no-apply cohort manifests, and—when `scripts/ci.py --base` is used—rejects rewrites or truncation of the narrative design-decision log, decision-event log, and run ledger relative to the PR base. Neither tool replaces tests, peer review, or GitHub branch protections.

## Operating loop

1. Read this directory and the applicable repository contracts before changing code.
2. Select the highest-priority unblocked task whose dependencies are complete.
3. Work in an isolated branch/worktree where practical; define the exact acceptance command before implementation.
4. Run the acceptance command, relevant regression suite, and an independent diff review.
5. Record immutable evidence references and update task/state/progress in the same change.
6. If blocked or repeatedly failing, record the blocker and replan rather than retrying unchanged.
7. Integrate only through a reviewable PR. Never merge to `main`, release, deploy production, change security settings, or perform destructive external actions without explicit owner authorization.

## Generated CI evidence artifacts

The fast workflow writes a raw `fast-ci-summary.json` from each selected suite's captured output and a derived `fast-ci-scorecard.json`. Both are uploaded as a run-scoped artifact. The summary records the PR-head SHA, workflow checkout SHA, base SHA, run ID/attempt, selected suites, per-suite exit status, output digest, elapsed time, and parsed test/skipped counts. Suites with no unittest count output retain explicit null/unknown counts rather than being treated as zero; project-control negative self-tests are reported separately.

The scorecard is recomputed from the raw summary, `RUN_LEDGER.jsonl`, and `PROGRESS.json`; it pins SHA-256 digests of those exact inputs. It retains failed, cancelled, and ineligible historical events, and verified claims must resolve to ledger event IDs. A scorecard that differs from those source-derived values is rejected. The artifact is diagnostic evidence; it does not mutate the repository ledger or declare a benchmark/capacity result by itself.
