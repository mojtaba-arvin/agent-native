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
- [check_claims.py](../scripts/check_claims.py): fail-closed validation for evidence-backed completion claims.

## Validate

Run:

```sh
python project_control.py validate
python project_control.py status
python scripts/check_claims.py
```

The control-plane validator checks structural invariants and cross-file references. The claims checker additionally requires verified completion claims to resolve to successful ledger events with immutable run, commit, or GitHub Actions run references, and requires every verified milestone criterion to map to exactly one such claim. Neither tool replaces tests, peer review, or GitHub branch protections.

## Operating loop

1. Read this directory and the applicable repository contracts before changing code.
2. Select the highest-priority unblocked task whose dependencies are complete.
3. Work in an isolated branch/worktree where practical; define the exact acceptance command before implementation.
4. Run the acceptance command, relevant regression suite, and an independent diff review.
5. Record immutable evidence references and update task/state/progress in the same change.
6. If blocked or repeatedly failing, record the blocker and replan rather than retrying unchanged.
7. Integrate only through a reviewable PR. Never merge to `main`, release, deploy production, change security settings, or perform destructive external actions without explicit owner authorization.
