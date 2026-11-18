# E-007 — Manual factorial pilot operator runbook

**Status:** one-shot marker-gated PR-synchronize dispatch is implemented; manual workflow_dispatch remains available.  
**Workflow:** [E-007 matched proposal-surface factorial pilot](../../.github/workflows/e007-real-agent-eval.yml)  
**Branch gate:** research/reboot-core only.

## Why dispatch is manual

The workflow provisions Ollama, pulls qwen3:8b, and may run for hours. It is excluded from ordinary push and PR-open triggers. A PR-synchronize event can reach the workflow only through a strict marker preflight; all model/provisioning steps are skipped unless the exact one-shot commit and manifest match. Do not convert it into ordinary CI and do not increase model/token/time budgets to compensate for protocol failures.

## Pre-dispatch checklist

1. Confirm the target branch is exactly research/reboot-core.
2. Confirm the workflow accepts manual workflow_dispatch or a PR-synchronize event on the research/reboot-core head branch; the preflight must validate the exact request ID, commit subject, four-cell manifest, Qwen3 model, and no-apply flag before provisioning.
3. Confirm the dispatch manifest validates all four matched cells A–D and their exact case paths/IDs.
4. Confirm the current pinned revision contains:
   - terminal stop on exhausted proposal-repair budget;
   - monotonic runner start/finish telemetry;
   - independent evaluator and trusted base reconstruction;
   - exact proposal/validate/plan hash continuity;
   - no-apply enforcement;
   - cohort guard that continues after task-level failures but aborts on shared infrastructure failure or unusable evidence.
5. Run deterministic E-007 and E-009 tests before model provisioning.
6. Record the exact workflow SHA, dispatch identity, model digest/modelfile, Ollama version, and dispatch time.
7. Do not run if any preflight check fails.

## Dispatch

Preferred route: use the [GitHub Actions workflow](https://github.com/mojtaba-arvin/agent-native/actions/workflows/e007-real-agent-eval.yml), choose **Run workflow**, select research/reboot-core, and start one cohort.

If the execution environment cannot call workflow_dispatch, use the marker-gated PR-synchronize route. Commit the exact manifest at `experiments/e007/dispatch-request.json` to the existing PR head on `research/reboot-core`, with the exact subject `experiment(e007): dispatch one bounded factorial cohort`. The workflow validates the PR head commit and marker through the GitHub API, checks the pinned model/budget/no-apply settings, and skips every model step for ordinary commits. It posts the run ID and artifact link to Issue #61 when the run completes. Never replay a consumed marker; use a new request ID only after verifying that the prior cohort did not consume model budget.

## Post-run acceptance audit

Do not treat a green workflow badge or non-empty candidate file as acceptance. Download and inspect the complete artifact and verify:

- all four A–D cells have provenance and complete raw traces;
- infrastructure-invalid trials are excluded from agent acceptance but retained in the artifact;
- candidate service ID and base revision match the trusted evaluator fixture;
- the exact same 64-character change_set_id appears on successful proposal, validation, and plan events;
- independent evaluator confirms exact preservation of every trusted base declaration and the requested change;
- plan is valid, will_mutate=false, and will_deploy=false;
- no service.apply call exists;
- per-cell token/tool/time budgets were respected;
- no missing or malformed trace has been silently scored as a failure or success.

A proposal-only result, accepted proposal without validation and safe plan, timeout, provider failure, or mock test is not E-007 lifecycle acceptance.

## Decision outputs

Report each cell separately: eligibility, task acceptance, hash continuity, preservation, safe-plan result, tokens, tools, elapsed time, provider failures, and missing telemetry. Compare A–D as a matched factorial only if the cohort is complete and infrastructure-valid. E is exploratory and must not be pooled into the 2×2 factorial.

No architecture decision should be made from a single successful run. Preserve failed artifacts and preregister any follow-up.
