# E-007 — Manual factorial pilot operator runbook

**Status:** one-shot marker-gated push dispatch is implemented; manual workflow_dispatch remains available.  
**Workflow:** [Agent Native CI](../../.github/workflows/ci.yml) — manual `workflow_dispatch`, select `model_suite=e007`.  
**Branch gate:** research/reboot-core only.

## Why dispatch is manual

The workflow provisions Ollama, pulls qwen3:8b, and may run for hours. It is deliberately excluded from push and pull-request triggers. Do not convert it into ordinary CI and do not increase the model/token/time budgets to compensate for protocol failures.

## Pre-dispatch checklist

1. Confirm the target branch is exactly research/reboot-core.
2. Confirm the workflow accepts only manual workflow_dispatch or the exact one-shot marker commit on research/reboot-core; no pull_request, schedule, or ordinary push trigger.
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

If the execution environment cannot call workflow_dispatch, the repository provides a one-shot push proxy. It requires the exact validated manifest at `experiments/e007/dispatch-request.json` and the exact commit subject `experiment(e007): dispatch one bounded factorial cohort`. The workflow rejects any other branch, commit subject, marker content, model, repetition count, or apply setting. Never replay the marker after the one-shot request has been consumed.

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
