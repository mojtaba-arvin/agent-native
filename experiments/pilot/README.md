# Agent Native — disposable agent-interface pilot

**Status:** protocol proposed; no agent trials have been run.  
**Scope:** one experiment, one variable, no product implementation decision.

## Decision being tested

The first pilot tests exactly one hypothesis:

> Progressive disclosure of a typed agent tool surface reduces invalid tool selection and total agent effort, without reducing task acceptance, compared with exposing the same complete tool surface and schemas up front.

This is deliberately narrower than testing whether Agent Native is better than FastAPI, whether a new language is worthwhile, or whether a new runtime is faster. Those questions cannot be answered by this pilot.

## Why this is the first pilot

E-005 already contains a small inspect/propose/validate/plan interface and a progressive-discovery mechanism. E-007 already defines a safe-change-planning task and provider-neutral trace format. Connecting these existing pieces tests a real unresolved assumption before building a service runtime.

The experiment is about the agent interface only. The backend state, service model, validator, available operations, tool semantics, task prompt, model settings, and evaluator must be identical between arms.

## Task

Use the existing E-007 `safe-change-plan` task against the small catalog service fixture used by E-005.

The agent must inspect the service, understand the requested change, produce a proposal against the supplied revision, validate it, and produce a plan. The plan must identify required effects and human approval gates. The prototype's apply operation remains disabled; no mutation or deployment is part of this pilot.

The service fixture, task prompt, validator version, and hidden acceptance oracle must be pinned by content hash before the first run. The oracle must remain outside the agent-visible workspace and process boundary, following `ORACLE_ISOLATION.md`.

## Experimental arms

Both arms use the same backend implementation and exactly the same six operations:

- `interface.describe`
- `service.inspect`
- `service.propose`
- `service.validate`
- `service.plan`
- `service.apply` (disabled)

**Arm A — progressive disclosure:** initially expose only compact tool summaries. The agent may request one detailed schema when needed. This uses the E-005 discovery model.

**Arm B — full upfront contract:** expose all six tool descriptions and complete input schemas at the beginning. No schema-fetch step is needed.

The only intended independent variable is schema-discovery policy. Do not change tool names, descriptions, schemas, ordering semantics, backend responses, error messages, model, prompt, or budgets between arms. If the implementation cannot preserve this equivalence, do not run the comparison.

## Protocol

1. Freeze and hash the task, service fixture, backend, schemas, evaluator, and both arm configurations.
2. Use the same pinned model identifier and inference settings in both arms. Record the exact provider/model revision where available.
3. Give both arms identical context, tool-call, token, wall-clock, and retry budgets.
4. Run paired trials: each pair uses the same task and model settings, with randomized arm order. Use fresh isolated state for every trial.
5. Start with 10 paired trials as a pipeline/screening check. If the harness, traces, and evaluator are valid, expand to at least 30 paired trials before making a directional decision. Do not describe the screening stage as statistically conclusive.
6. Preserve every raw trace, including failed, timed-out, and incomplete trials. Never drop a run because it makes an arm look worse.
7. Evaluate artifacts in a separate trusted evaluator. Return only public failure classes to the agent; never reveal hidden assertions.
8. Publish per-arm raw distributions and paired differences. Report uncertainty intervals; do not reduce the result to a single composite score.

## Measurements

Primary outcome:
- task acceptance rate under the hidden oracle.

Primary efficiency outcomes:
- total input and output tokens;
- total inference cost, where provider telemetry is available;
- total tool calls;
- invalid/unknown tool calls and schema/argument errors;
- wall-clock time;
- repair events and repeated attempts;
- human interventions;
- cost per accepted task.

Safety and integrity gates:
- any unauthorized effect or mutation is an automatic stop;
- any oracle leakage or evaluator/agent boundary breach invalidates the entire run;
- any difference in backend semantics or task difficulty invalidates the comparison;
- missing telemetry is marked incomplete, never silently treated as zero.

## Pre-registered decision gates

These are screening thresholds for this pilot, not universal product requirements.

**Continue to a larger study** only if all are true:
- no oracle leakage, unauthorized effect, or mutation occurs;
- the progressive arm's acceptance rate is not more than 5 percentage points below the upfront arm;
- invalid tool/schema calls fall by at least 25% relative to the upfront arm;
- cost per accepted task improves by at least 10%, or the paired data gives a credible path to that improvement without an acceptance penalty.

**Change the interface design** if acceptance is preserved but the invalid-call or cost outcomes do not meet the thresholds. Inspect raw traces to identify whether the discovery step adds overhead, hides necessary context, or causes extra round trips.

**Stop this hypothesis** if progressive disclosure causes a material acceptance regression, increases cost per accepted task, or produces no meaningful reduction in invalid calls after the expanded study. Do not defend it by adding unrelated abstractions.

**Inconclusive** is a valid outcome. If intervals are too wide or telemetry is incomplete, collect better evidence or stop; do not claim success.

## Explicitly out of scope

- Building a production service or a first framework release.
- Choosing a language, DSL, IR, compiler, runtime, protocol, or deployment model.
- Comparing FastAPI or another existing framework.
- Adding CRUD execution, persistence, networking, distributed transactions, or production mutation.
- Implementing a general-purpose agent runner, sandbox, or model-provider integration as part of this pilot.
- Testing multiple runtimes, multiple agent protocols, or multiple independent design variables at once.

## Stop conditions and cleanup

The pilot is disposable. If the hypothesis fails, preserve the task, traces, evaluator results, and a short negative-result record; remove or archive pilot-only implementation code. Do not promote pilot code into the framework core merely because it exists.

No trial result may be claimed until actual agent executions have been performed in an isolated environment and independently evaluated. The current E-005 prototype is in-process and is not itself a sandbox.

## Current state

- Protocol: specified here.
- Task source: E-007 `safe-change-plan`.
- Candidate interface: E-005.
- Hidden evaluator: not yet provisioned.
- Isolated agent/evaluator runner: not yet provisioned.
- Agent trials: **not run**.
- Architecture or technology selection: **none**.
