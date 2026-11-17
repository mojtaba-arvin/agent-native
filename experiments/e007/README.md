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

## Corrective changes and remaining limits

The E-005 tool schema now publishes the full canonical IR object; `AN021` adds an actionable fix hint; the E-009 task and system prompt require a complete snapshot, not a patch; and the local runner blocks `service.plan` until the current proposal hash has `result.valid=true`. These changes pass deterministic tests, but a post-fix real-model run is still required.

This is the first executable single-case eval loop, not the full ten-task benchmark. It does not execute arbitrary agent-generated code and is not a general-purpose sandbox or private oracle service. The task manifest, workspace preparation, trace schema, metric aggregation, and first eval case are executable. The general isolated evaluator and hidden E-007 oracle package remain unimplemented. The proposed multi-tier/model cohort and expanded task design are future work only: [E-007 future evaluation plan](../../research/e007-future-evaluation-plan.md).
