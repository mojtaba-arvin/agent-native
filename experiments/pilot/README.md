# Agent Native — disposable agent-interface pilot

**Status:** local execution adapter and protocol checks implemented; no real model trials or evaluator-backed results have been recorded.  
**Scope:** one experiment, one variable, no product implementation decision.

## Decision being tested

The first pilot tests exactly one hypothesis:

> Progressive disclosure of a typed agent tool surface reduces invalid tool selection and total agent effort, without reducing task acceptance, compared with exposing the same complete tool surface and schemas up front.

This is deliberately narrower than testing whether Agent Native is better than FastAPI, whether a new language is worthwhile, or whether a new runtime is faster. Those questions cannot be answered by this pilot.

## Why this is the first pilot

E-005 already contains a small inspect/propose/validate/plan interface and a progressive-discovery mechanism. E-007 provides a provider-neutral trace format and aggregation logic. The pilot adds one narrowly scoped task that the current E-005 prototype can actually express. This tests a real unresolved assumption before building a service runtime.

The experiment is about the agent interface only. The backend state, service model, validator, available operations, tool semantics, task prompt, model settings, and evaluator must be identical between arms.

## Task

Use the pilot-specific task in `TASK.md` against the E-005 Catalog fixture. The task is intentionally limited to a change the current prototype can represent: add one read-only `get_item_by_name` operation while preserving the existing service contract. The task requires the agent to inspect the service, produce a proposal against the supplied revision, validate it, and produce a no-side-effect plan.

Do **not** use E-007 `safe-change-plan` for this pilot. That task requires destructive migration planning, rollback detail, and external-egress authority semantics that the current E-005 prototype does not represent. Reusing it would make the pilot invalid by asking the candidate to do work its interface cannot express.

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

## Common dispatch adapter

Both arms use one common `agent.invoke` dispatch envelope containing the same tool-name enum, request identifier, and arguments object. The envelope is intentionally generic; the E-005 handler remains responsible for strict per-tool argument validation and stable diagnostics. This holds the invocation mechanism constant while varying only the schemas initially shown to the agent.

- `surface.py` builds the progressive and upfront manifests from the single canonical `experiments/e005/tools.json` catalog and checks that tool identity, descriptions, dispatch schema, and discovery schema are equivalent.
- `gateway.py` is a local newline-delimited JSON (NDJSON) adapter. It emits the session manifest, accepts calls to only the six E-005 operations, and delegates them to the same in-process E-005 reference handler. It offers no shell, filesystem, arbitrary network, secret, or deployment operation.
- `candidate.schema.json` defines the agent final-output artifact; `evaluation-result.schema.json` defines the coarse result the trusted evaluator returns. `candidate.py` validates only the public envelope, recomputes the content-addressed proposal ID, and can require that ID to appear in a successful `service.propose` trace event. It is not the acceptance oracle and does not decide whether the requested operation is correct.
- In the progressive arm, `interface.describe` is available with the same schema as the upfront arm and can return a selected tool's detailed schema. In the upfront arm, every detailed schema is included in the initial session manifest.
- The gateway can write one exclusive, mode-0600 JSONL trace per run. It records task start, initial surface payload bytes, tool calls, explicit named-schema lookups, stable failure codes, and the content hash of a successful proposal without recording tool arguments or proposal bodies. The trusted outer runner/evaluator—not the agent—must append the authoritative `task_finished` event. Provider token/cost telemetry must come from the provider adapter, not be inferred by this gateway.

Example gateway launch:

```sh
python experiments/pilot/gateway.py \
  --arm progressive \
  --run-id trial-001 \
  --model-id '<pinned-model-id>' \
  --max-input-tokens 16000 \
  --max-output-tokens 4000 \
  --max-tool-calls 40 \
  --trace-output /secure/path/trial-001.jsonl
```

The experimental arm identity is not included in the model-visible session manifest; it is retained only in out-of-band trace metadata. This avoids telling the agent which treatment it received. The surface and trace metadata are separate objects.

This gateway makes the tool contract executable and testable. The bounded local Ollama runner described below now performs real model requests and routes tool calls through this gateway. Neither component is part of the Agent Native product, neither enforces a general-purpose OS sandbox, and neither evaluates acceptance. The separate trusted evaluator remains a prerequisite for any accepted/rejected benchmark result. The common dispatch envelope is an experimental measurement adapter, not a decision about Agent Native's eventual public protocol.

## Paired trial schedule

`schedule.py` creates an immutable runner-only schedule. It pairs one progressive and one upfront run for each pair, randomizes their order with a recorded seed, places the two runs adjacent, and schedules only one trial at a time. The plan pins:

- the clean Git HEAD (the CLI resolves it itself and refuses a dirty worktree);
- SHA-256 hashes of the system prompt, task, public oracle contract, service fixture, E-001/E-005 implementation, tool catalog, gateway, candidate/result contracts, finalizer, schedule generator/verifier, and trace/metrics contracts;
- exact model identifier and generation-settings JSON;
- identical input/output token, tool-call, and wall-clock budgets;
- a deterministic plan ID and run ID for every arm/pair.
- enforced gateway input/output-token and tool-call ceilings, unique provider-usage message IDs, and monotonic per-run timestamps.

Before executing any trial, verify the schedule from the same clean checkout:

```sh
python experiments/pilot/verify_schedule.py \\
  --schedule /secure/path/pilot-screening-schedule.json
```

The verifier checks the schedule hash, exact Git HEAD, clean working tree, and every pinned source-file hash. The full schedule contains treatment labels and is strictly runner-side metadata. Do not place the schedule file in the agent workspace or pass `candidate_id`, pair order, seed, or treatment label to the model. The model receives the byte-identical system prompt, task prompt, and the selected session surface. The model generation settings must be identical across both arms; do not put credentials in the settings file.

Example (screening only):

```sh
python experiments/pilot/schedule.py \
  --pairs 10 \
  --seed 20261116 \
  --model-id '<exact-provider-model-revision>' \
  --generation-settings-file /secure/path/pilot-generation-settings.json \
  --max-input-tokens 16000 \
  --max-output-tokens 4000 \
  --max-tool-calls 40 \
  --max-wall-seconds 900 \
  --output /secure/path/pilot-screening-schedule.json
```

The settings file must be a JSON object containing the provider's non-secret generation parameters. The runner must pass each selected trial's `budgets.max_tool_calls` to `gateway.py`; traced gateway sessions reject startup without this positive limit. The output path is exclusive: an existing schedule is never overwritten. For confirmatory trials, use at least 30 pairs and a separately recorded seed; do not reuse a screening schedule.

Keep the schedule and generation-settings file outside the repository checkout: the scheduler refuses a dirty worktree and the schedule contains treatment labels. `AGENT_ADAPTER.md` specifies the provider-neutral bridge and insists on exactly one identical provider-facing `agent.invoke` function in both arms.

The schedule generator itself does not call a model or execute a trial. The repository now includes a separate, bounded local Ollama runner for one scheduled trial at a time. A separately protected evaluator deployment remains necessary before any trial can be scored for acceptance. This pilot does not execute agent-generated code: the model proposes JSON service IR through the allowlisted gateway. Therefore a general-purpose OS sandbox for generated code is not needed for this narrow trial; the evaluator implementation, private keys, and detailed results must nevertheless remain outside model context and outside this public repository.

## Execute real local-model trials

The pilot includes ollama_runner.py, a local-only runner for Ollama's native /api/chat tool-calling API. It accepts only a loopback HTTP endpoint, defaults to http://127.0.0.1:11434, and exposes one model-visible function: agent.invoke. The runner verifies the immutable schedule and clean source checkout before every trial, launches a fresh gateway, enforces the scheduled budgets, records provider token usage, and stores artifacts outside the checkout with restrictive permissions.

The runner requires explicit Ollama generation settings so model defaults do not silently vary between arms. Save this file outside the repository:

```json
{
  "temperature": 0.2,
  "top_p": 0.9,
  "seed": 20261117,
  "num_ctx": 8192,
  "think": true
}
```

Use the exact local model identifier shown by ollama list. For the existing local Qwen 3 installation, the example identifier is qwen3-8b-local; confirm the exact tag on the machine before creating the schedule.

First create a one-pair wiring check (two trials, one per arm). This checks the complete local model-to-gateway path; it is not benchmark evidence:

```sh
python experiments/pilot/schedule.py \
  --pairs 1 \
  --seed 20261117 \
  --model-id qwen3-8b-local \
  --generation-settings-file /secure/path/ollama-settings.json \
  --max-input-tokens 16000 \
  --max-output-tokens 4000 \
  --max-tool-calls 40 \
  --max-wall-seconds 900 \
  --output /secure/path/pilot-wiring-check.json

python experiments/pilot/run_schedule.py \
  --schedule /secure/path/pilot-wiring-check.json \
  --results-dir /secure/path/pilot-wiring-runs \
  --require-candidate-ready
```

The wiring-check flag returns a nonzero exit status unless both arms produced a parseable candidate whose proposal ID is present in that run's gateway trace. This verifies protocol readiness only; it does not assert task acceptance.

Only after the wiring check succeeds, create a fresh 10-pair screening schedule with a new seed and run all 20 sequence numbers serially:

```sh
python experiments/pilot/schedule.py \
  --pairs 10 \
  --seed 20261118 \
  --model-id qwen3-8b-local \
  --generation-settings-file /secure/path/ollama-settings.json \
  --max-input-tokens 16000 \
  --max-output-tokens 4000 \
  --max-tool-calls 40 \
  --max-wall-seconds 900 \
  --output /secure/path/pilot-screening-schedule.json

python experiments/pilot/run_schedule.py \
  --schedule /secure/path/pilot-screening-schedule.json \
  --results-dir /secure/path/pilot-screening-runs
```

Each run directory contains the raw gateway trace, the model's final response, the candidate artifact when it is parseable, and a run.json manifest. The manifest reports either candidate_ready_for_external_evaluation or a classified failure. It never claims acceptance. Do not reuse run directories or run IDs, and preserve failed runs.

**Current evidence boundary:** CI validates the adapter against a deterministic local HTTP test double. That proves protocol handling, trace recording, and budget wiring—not model quality. Actual Ollama trials must be run on a machine with the pinned local model. The private evaluator must then independently score each candidate before acceptance rates or comparative results can be published.

## Evaluate and analyze a completed study

A batch marked `completed` means every scheduled model invocation returned a run record; it does not mean the agent solved the task. After the private evaluator has been deployed separately, evaluate each immutable run after the model has stopped. Keep the evaluator source outside this public checkout and outside model-visible context.

For each run directory, the private evaluator consumes the schedule entry, raw `gateway.jsonl`, `run.json`, and `candidate.json` when present. It writes only the coarse `evaluation-result.json`. Then use the public finalizer to bind that result to the original trace:

```sh
python experiments/pilot/finalize.py \
  --trace /secure/path/pilot-runs/<run-id>/gateway.jsonl \
  --evaluation-result /secure/path/pilot-runs/<run-id>/evaluation-result.json \
  --candidate /secure/path/pilot-runs/<run-id>/candidate.json \
  --output-trace /secure/path/pilot-runs/<run-id>/finalized.jsonl \
  --output-summary /secure/path/pilot-runs/<run-id>/summary.json
```

Omit `--candidate` when the run produced no candidate. Do not create or edit a `task_finished` event by hand; the finalizer appends it only after checking the evaluator result and trace/candidate identities.

Once every scheduled run has a `finalized.jsonl`, generate the paired analysis:

```sh
python experiments/pilot/analyze.py \
  --schedule /secure/path/pilot-screening-schedule.json \
  --results-dir /secure/path/pilot-screening-runs \
  --output /secure/path/pilot-screening-analysis.json
```

The analyzer verifies the schedule against the clean pinned checkout, requires every scheduled run exactly once, checks trace identities, and refuses missing or incomplete finalized traces. It reports per-arm acceptance and effort summaries, paired upfront-minus-progressive differences, deterministic 95% paired-bootstrap percentile intervals, exact two-sided McNemar results for acceptance, and the E-007 aggregate. Infrastructure-excluded pairs are reported and omitted from primary paired acceptance and effort estimates. Preserve the schedules, raw traces, candidates, evaluation results, finalized traces, per-run summaries, batch manifest, analysis JSON, and evaluator version together as the immutable study record.

The analysis is descriptive evidence for the registered task and model only. A screening run is not enough to select a framework design; use the pre-registered confirmatory repetitions and the broader E-007 corpus before drawing general conclusions.

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
- Task source: pilot-specific `TASK.md`, constrained to the E-005 capability.
- Candidate interface: E-005.
- Equivalent blinded arm manifests, fixed system prompt, common NDJSON gateway with enforced input/output-token and tool-call ceilings, replay-safe provider-usage telemetry, monotonic timestamps, strict candidate-artifact envelope checks, same-proposal trace correlation through propose/validate/plan, validation/no-side-effect gates, E-007 tool-error/schema-lookup and infrastructure-eligibility metrics, deterministic paired schedules and clean-checkout verification, public oracle contract, and provider-neutral adapter contract: implemented.
- Deterministic mock conformance tests exercise both the complete gateway-to-finalizer-to-metrics path and the gateway's real CLI subprocess protocol. Their synthetic provider/evaluator results are test scaffolding only; they are not AI-agent trials or acceptance evidence.
- GitHub Actions protocol checks: running on current branch head; no agent trial has been performed.
- Public acceptance-oracle contract: specified in ORACLE_CONTRACT.md; evaluator implementation must remain private and external.
- Provider-specific model adapter and protected evaluator implementation/deployment: not provisioned.
- Agent trials: **not run**.
- Architecture or technology selection: **none**.
