# E-007 agent task corpus and trace metrics

Ten public task statements cover service contracts, schema evolution, tenant isolation, idempotency, deadlines/retries, streaming/backpressure, durable recovery, capability security, regression repair, and safe change planning.

**Oracle isolation:** acceptance oracles must be mounted by a separate evaluator outside the agent-visible workspace. This public corpus contains task prompts and oracle identifiers only; it intentionally does not include hidden assertions. See [ORACLE_ISOLATION.md](ORACLE_ISOLATION.md) for the required trust boundaries.

`prepare_workspace.py` materializes exactly one public task into a minimal agent-visible workspace and excludes oracle identifiers and other task prompts. It does not run an agent or provide a sandbox.

`trace.schema.json` defines a provider-neutral trace event envelope. For comparative trials, events should include a stable `run_id`, `candidate_id`, and `model_id`. All events for one candidate/task execution share the same `run_id`; the aggregator groups by `run_id`, `task_id`, and `attempt`. This prevents repeated runs or different candidate arms from being merged into one result. These identity fields remain optional for older traces; legacy traces are grouped by task and attempt.

`metrics.py` aggregates input/output tokens, tool calls, repair events, human interventions, inference cost, wall time, acceptance, runtime metrics, and cost per accepted task. Run it with:

```sh
python experiments/e007/metrics.py --input trace.jsonl --output summary.json
```

Provider adapters must preserve raw traces and must not invent missing token or cost values. Missing telemetry is reported as incomplete, not silently converted to zero. Trusted terminal events may carry `eligible_for_acceptance`; when omitted by legacy traces it defaults to true. Infrastructure-invalid trials can be retained with `eligible_for_acceptance: false`, allowing `task_count` and raw traces to include them while `acceptance_rate` uses only `eligible_task_count`. Accepted events cannot be marked ineligible. The trusted finalizer, not the agent, sets this flag from the coarse evaluator result. Candidate and model labels are carried into each per-run task result; compare candidates using those labels rather than pooling all runs. A failed tool invocation is recorded as a `tool_call` event with its stable diagnostic code in `failure_class`; arguments and response bodies are not required in traces. The aggregator reports `tool_errors`, `invalid_tool_calls`, `schema_argument_errors`, `schema_lookup_calls` (events explicitly marked as named-schema retrievals; listing compact discovery metadata is not counted), and per-class counts. It also reports `eligible_task_count` and `excluded_task_count` separately from `task_count`; excluded infrastructure failures remain visible and are not treated as agent task failures. `UNKNOWN_TOOL`, malformed request envelopes, invalid request IDs, invalid JSON/UTF-8, oversized messages, duplicate JSON keys, non-finite values, and schema/argument rejections are counted as invalid calls; business-level rejections such as a stale revision remain tool errors but are not classified as malformed calls. Successful `service.propose`, `service.validate`, and `service.plan` tool-call events may carry only the same 64-character `change_set_id` hash (never the proposal body); this lets a trusted evaluator correlate the final candidate with the exact proposal that was validated and planned by the gateway.

## First executable real-agent eval case

`evals/e009-readonly-proposal.eval.json` defines one structured complete-IR proposal task using the integrated E-009 Agent Gateway. `eval_runner.py` invokes the real `local_agent.py` Ollama adapter, preserves per-run traces/candidates, applies three deterministic scorers (candidate contract, proposal/validation/plan hash continuity, and behavioral safety), emits E-007 telemetry, and returns non-zero if a required scorer fails.

The case pins per-run input/output/token/tool/wall ceilings and an aggregate token/time budget. Before starting each repetition, the runner reserves the configured worst-case allowance. If the next run cannot fit, it records the remaining repetitions as `not_started`, marks them ineligible, and classifies them as `resource_budget_exceeded`, not an agent failure. Unknown provider usage fails closed before another repetition. Monetary cost is estimated only when explicit token tariffs are configured. Local Ollama is marked `unpriced_local`; currency cost is unknown, not zero. A mock integration test exercises the over-budget path.

## First three-run Qwen3 result — not accepted

The corrected real-model workflow [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547), artifact [14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550), ran `qwen3:8b` via Ollama three times. All three attempts failed at `service.validate` with `AN021`:

| Attempt | Result | Input tokens | Output tokens | Duration |
|---|---|---:|---:|---:|
| 1 | Failed — AN021 | 35,984 | 1,602 | 894.95 s |
| 2 | Failed — AN021 | 35,984 | 1,602 | 843.78 s |
| 3 | Failed — AN021 | 35,984 | 1,602 | 844.69 s |

The input declaration was already the correct array containing `name`, `source`, and `type`. The submitted IR was incomplete: it omitted top-level `ir_version=1` and included only the new operation rather than all existing operations plus the requested one. The validator therefore rejected the top-level shape with AN021. The semantic response had outer `ok=true` but `result.valid=false`; the model then called plan rather than repairing the IR. The successful-proposal repair limit was not exhausted, although the runs approached the 900-second wall ceiling.

All attempts used temperature 0 and seed 42 and generated matching token counts/tool paths. The Ollama server log confirms prompt/KV prefix-cache reuse; it does not show response-cache replay. These are three deterministic reproductions of one failure path, not independent statistical observations. Currency inference cost was not priced for local Ollama. The earlier standalone E-009 trial [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833) is a separate older failure in which the operation input was an object; this later artifact had a correct input array but an incomplete top-level IR.

## One stochastic post-fix probe — still not accepted

Workflow [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), artifact [14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630), used `temperature=0.7` and seed `20261117` for one exploratory attempt. It consumed 44,377 input and 1,399 output tokens and reached the 900-second wall ceiling; Ollama cancelled the active request and returned HTTP 500 at the boundary. This is a wall-time cancellation/provider HTTP symptom, not evidence of an arbitrary network disconnect or OOM. Currency cost is unpriced for local Ollama.

The model generated the full top-level IR shape (`ir_version=1`, service, types, seven operation entries) and the new operation's array input correctly. However, it changed five existing operation declarations rather than preserving the inspected versions. Its first proposal was rejected by the Gateway with `INSPECTION_INCOMPLETE`; after inspecting all six existing operations, it did not submit a second proposal before the wall budget expired. No successful proposal, validation, or plan occurred. The proposal payload and six inspection results are preserved in the raw trace. See the [stochastic probe analysis](results/2026-11-17-stochastic-qwen3-probe.md).

This one run establishes a different failure path under non-zero temperature; it does not establish improvement, statistical reliability, or model superiority. The later candidate-preservation code was committed after this workflow, so this particular run did not save a separate final candidate JSON.

## Post-Gateway deterministic probe — input-budget exhaustion

Workflow [44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813), artifact [14357367813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813/artifacts/14357367813), used Qwen3 with `temperature=0`, `seed=42`, and a 1,200-second wall cap. It consumed 48,307 input tokens against a 48,000 cap, 1,373 output tokens, and 1,020.139 seconds. The model inspected five of six existing operations; its first proposal was rejected with `INSPECTION_INCOMPLETE`; the input-token cap stopped the run before a second proposal, validation, or plan. No `AN021`, provider error, or observed OOM occurred. See the [raw-trace analysis](results/2026-11-17-deterministic-postfix-budget-exhaustion.md).

The artifact's original `eligible_for_acceptance=true` was incorrect: per-run token-budget exhaustion must be ineligible for the agent-acceptance denominator. The runner now excludes per-run input/output/tool/wall/model-turn/candidate-size budget stops, with regression coverage. The raw artifact remains unchanged. One bounded follow-up is running as [workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970) with a 96,000-input-token and 1,800-second wall budget; no IR or safety gate is relaxed.

## Corrective changes and remaining limits

The E-005 tool schema now publishes the full canonical IR object; `AN021` adds an actionable fix hint; the E-009 task and system prompt require a complete snapshot, not a patch; and the local runner blocks `service.plan` until the current proposal hash has `result.valid=true`. These changes pass deterministic tests, but a post-fix real-model run is still required.

A new one-run deterministic probe after the E-009 Gateway began enforcing exact preservation of inspected base declarations is running as [workflow 44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813). It uses `temperature=0`, `seed=42`, and a 1,200-second wall cap (rather than the previous 900-second cap). The dedicated case and workflow pin these settings. Its result remains pending until the raw artifact and Ollama daemon log are inspected; CI success alone is not real-model acceptance.

This is the first executable single-case eval loop, not the full ten-task benchmark. It does not execute arbitrary agent-generated code and is not a general-purpose sandbox or private oracle service. The task manifest, workspace preparation, trace schema, metric aggregation, and first eval case are executable. The general isolated evaluator and hidden E-007 oracle package remain unimplemented. The proposed multi-tier/model cohort and expanded task design are future work only: [E-007 future evaluation plan](../../research/e007-future-evaluation-plan.md).
