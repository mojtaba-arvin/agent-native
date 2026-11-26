# E-007 — Manual factorial pilot operator runbook

**Status:** the historical one-shot push-proxy route is retired. The frozen factorial manifest is prepared for the current manual workflow dispatch; it has not been run.  
**Canonical workflow:** [Agent Native CI](../../.github/workflows/ci.yml) — the E-007 lane is entered only by `workflow_dispatch` with `model_suite=e007`.  
**Required dispatch ref:** `research/reboot-core`.  
**Evidence class:** exploratory CPU-only model diagnostic; it does **not** satisfy M3 decision-grade acceptance.

## Purpose and execution boundary

E-007 is one matched, no-apply 2×2 factorial feasibility pilot. It compares proposal mode (snapshot/delta) with base disclosure (per-operation/upfront-full) across the four preregistered cells A–D. It is not a production deployment, a mutation test, or proof that the framework has passed M3.

The E-007 preflight and model jobs in `.github/workflows/ci.yml` are gated on a manual `workflow_dispatch` event and `model_suite=e007`. Ordinary push, pull-request, and scheduled runs do not start the E-007 model cohort. The workflow's separate scheduled acceptance lane remains independent; a manual E-007 run cannot count toward the seven consecutive successful Nightly runs required by V1.

Do not convert the model cohort into ordinary CI. Do not increase repetitions, model/token/tool/time budgets, or alter the factorial design to compensate for failures.

## Frozen dispatch contract

The source of truth is `experiments/e007/dispatch.json`, validated by `experiments/e007/validate_factorial_dispatch.py`. Treat the manifest and its referenced case files as preregistered inputs, not editable operator settings.

The current manifest specifies:

- Model: `qwen3:8b`; one repetition per cell; tool-schema arm `upfront`.
- Four matched cells: A = snapshot/per-operation; B = delta/per-operation; C = snapshot/upfront-full; D = delta/upfront-full.
- Fixed settings: temperature 0, top_p 1, seed 42, context 16384, and num_predict 2048.
- Per-run ceilings: 120000 input tokens, 6000 output tokens, 20 tool calls, and 3000 seconds.
- `no_apply=true`; no apply or deploy operation is permitted.
- Fixed execution order C, A, D, B, derived from the preregistered randomization seed 20261118. Do not reorder cells or adapt later cells to interim results.

The validator must accept the complete manifest and all four case files before the first model request. The runner also pins the workflow commit in a detached worktree and refuses to run unless the selected ref is exactly `research/reboot-core`.

## Historical dispatch route — permanently retired

The former one-shot push-proxy mechanism is obsolete. Its historical marker was consumed and must not be replayed or recreated. Do not create `dispatch-request.json`, do not make a marker commit, and do not attempt to trigger the cohort through a push, commit subject, or any other proxy.

The canonical route is the repository's current `.github/workflows/ci.yml` manual `workflow_dispatch` input. The presence of `experiments/e007/dispatch.json` is the frozen experiment manifest; it is not a workflow trigger or a replacement marker.

## Pre-dispatch checks

Before initiating a manual run, verify all of the following against the exact base revision:

1. The workflow ref selected for the dispatch is exactly `research/reboot-core`. Select the branch explicitly; do not use a feature branch or a pull-request ref.
2. The workflow is `.github/workflows/ci.yml`, the event is `workflow_dispatch`, and the `model_suite` input is `e007`.
3. `experiments/e007/dispatch.json` is unchanged from the preregistered manifest and reports `ready_for_manual_dispatch` with `no_apply=true`.
4. `python experiments/e007/validate_factorial_dispatch.py` validates exactly the four matched cells, their case paths/IDs, common task identity, settings, budgets, and fixed execution order.
5. `bash -n experiments/e007/run_factorial_pilot.sh` succeeds.
6. The pinned revision contains the required proposal/disclosure runner and trusted evaluator/oracle support. The runner's preflight checks must pass.
7. Record the workflow run URL/ID, exact source SHA, dispatch identity, model digest and Modelfile, Ollama version, and dispatch timestamp with the resulting evidence.

The workflow runs deterministic E-007 and E-009 preflight tests before provisioning Ollama. It then installs Ollama and pulls Qwen3 before invoking the factorial runner. The runner enforces the exact branch and pinned-commit checks before any factorial cell is executed. Therefore, selecting the correct branch before dispatch is mandatory; do not rely on a later runner rejection to validate the operator's branch choice.

If any manifest, deterministic preflight, branch, pinned-source, or oracle-support check fails, stop. Do not edit the frozen manifest or increase budgets to force a run.

## Post-run artifact audit

A green workflow conclusion alone is not acceptance. Inspect the complete uploaded artifact and the raw evidence for every cell. Retain failed, incomplete, and infrastructure-invalid evidence; never silently discard it or score missing telemetry as a pass.

For each of A, B, C, and D, verify and report:

- The cell has its own complete result and raw trace, with provenance tying it to the same workflow run and pinned source SHA.
- Model identity/digest, Modelfile, Ollama version, dispatch identity, case identity, and all effective settings match the preregistration.
- Input/output token, tool-call, and wall-clock use remain within the frozen per-run ceilings.
- Candidate service ID and base revision match the trusted evaluator fixture.
- Successful proposal, validation, and safe-plan events carry the exact same 64-character `change_set_id`.
- The independent evaluator confirms preservation of every trusted base declaration and the requested change.
- The final plan is valid and explicitly reports `will_mutate=false` and `will_deploy=false`.
- No `service.apply` call or other mutation/deployment action appears in any trace.
- Missing, malformed, timed-out, provider-failed, and infrastructure-invalid trials are classified according to the runner's guard contract, not silently converted into agent failures or successes.

The matched cohort is complete only when all four cells have usable evidence. The runner continues after an individual agent/task failure so the matched cohort can be analyzed, but aborts on shared infrastructure failure or unusable evidence. A partial cohort is not a completed factorial comparison.

A proposal-only result, a proposal without successful validation and a safe plan, broken hash continuity, failed trusted preservation, any mutation/deployment attempt, timeout, provider failure, missing artifact, or mock test is not E-007 lifecycle acceptance.

## Reporting and decision rules

Report each cell separately: eligibility, task acceptance, hash continuity, trusted-state preservation, safe-plan result, token/tool/time use, provider failures, infrastructure validity, and missing telemetry. Compare A–D as a matched factorial only when the complete cohort is infrastructure-valid. The minimal-disclosure E treatment is exploratory and must not be pooled into this 2×2 factorial.

Do not infer an architecture decision from one successful run. Preserve all raw artifacts and negative results, state limitations, and preregister any follow-up before collecting more measurements.

## Relationship to M3 and V1

This workflow's model job is explicitly named **Layer 2 · manual CPU diagnostics (not M3 acceptance)**. Its own run summary states that CPU-only model evidence is exploratory and does not satisfy M3 decision-grade acceptance. Do not describe a successful E-007 CPU diagnostic as passing M3 or as completing V1.

M3 decision-grade acceptance requires its separately defined evidence and trust-boundary conditions; it is not substituted by this runbook, a green manual workflow, or four locally passing cells. V1's seven-consecutive-night Nightly gate is also independent and must be demonstrated on the base branch.
