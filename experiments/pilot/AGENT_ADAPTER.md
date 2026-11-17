# Pilot agent-adapter contract

**Status:** provider-neutral contract; no provider implementation is selected or included.

The adapter is the trusted bridge between a model-provider API and the local E-005 pilot gateway. It is not part of the Agent Native product and must not become a permanent framework abstraction merely because the pilot needs it.

## Trust boundary

The model provider receives only:
- the exact system prompt from `PROMPT.md`;
- the pilot task prompt;
- the model-visible session surface for its assigned trial;
- prior tool results from that same trial;
- the provider's own generation configuration.

The model provider must never receive:
- the schedule file or pair order;
- the treatment label (`progressive` or `upfront`);
- hidden acceptance assertions, oracle identifiers, evaluator prompts, or evaluator results;
- local trace paths, candidate hashes before final submission, credentials, or evaluator environment metadata.

The trusted adapter holds provider credentials. Credentials must never be placed in the prompt, tool result, tool schema, trace, task workspace, candidate artifact, or evaluator result.

The adapter and gateway may receive a run-scoped identifier and candidate label as out-of-band metadata. Those fields are not copied into model-visible messages.

This is a tool-use experiment, not a code-execution benchmark: the model proposes a JSON service IR and the E-005 gateway stores/validates/plans it without executing it. A general-purpose sandbox for model-generated code is therefore outside this pilot. The trusted evaluator still runs separately from the model-facing adapter, never exposes its implementation or keys to the model, and must not execute candidate data.

## Trial startup

1. Before starting any trial, the runner executes `verify_schedule.py` from the clean checkout and verifies the schedule Git revision and all pinned source hashes. A mismatch aborts the entire batch before any model request.
2. The runner selects exactly one trial from the verified immutable schedule.
3. The runner creates a fresh E-005 gateway instance and a new exclusive trace file for that run, passing the trial's exact `max_tool_calls` value to `gateway.py`.
4. The runner starts the gateway with its out-of-band run ID, candidate ID, model ID, task ID, and attempt number.
5. The adapter reads the gateway's first NDJSON message, which contains the session surface. It must not add or remove tool schemas.
6. The runner supplies the task text from `experiments/pilot/TASK.md`. It does not supply the pair ID, trial order, candidate label, hidden evaluator data, or schedule.
7. The adapter sends the exact system prompt from `PROMPT.md`, the task text, and the session surface to the selected model using the exact generation settings pinned in the schedule. The system prompt and task text must be byte-identical across both arms; only the initial session surface differs.

## Tool-call mapping

Both arms expose the same generic dispatch contract named `agent.invoke`:

```json
{
  "request_id": "unique-per-call",
  "tool": "service.inspect",
  "arguments": {
    "service_id": "catalog"
  }
}
```

The provider-facing API must expose exactly one function/tool, named `agent.invoke`, in both arms, using the exact `dispatch.input_schema` from the session surface. Do not expose the six E-005 operations as six separate provider functions: that would change the provider tool count and confound this experiment. The adapter includes the `surface.tools` list and `schema_discovery` object as a structured JSON context block. Thus the only initial-context difference is the presence or absence of non-discovery input schemas; the provider-native function declaration and invocation path remain byte-for-byte identical.

The adapter maps a model `agent.invoke` call to one NDJSON gateway line:

```json
{
  "type": "tool_call",
  "request_id": "unique-per-call",
  "tool": "service.inspect",
  "arguments": {
    "service_id": "catalog"
  }
}
```

It reads exactly one `tool_result` message and returns the nested E-005 response to the model as the tool result. It must preserve tool names, arguments, diagnostic codes, and result values. It must not retry, rewrite, repair, or silently normalize an invalid model call. Provider-required serialization is allowed only if semantically lossless and identical in both arms.

The adapter must enforce the scheduled wall-clock limit and stop on a gateway budget rejection. The gateway independently enforces the scheduled maximum tool-call count, its request-size limit, and tool allowlist. The runner must launch it with the trial's exact `max_tool_calls` value from the schedule; traced runs refuse to start without a positive cap. The over-budget call is traced as `TOOL_CALL_BUDGET_EXCEEDED`, is never dispatched, and maps to the eligible agent failure class `AGENT_BUDGET_EXHAUSTED`. The model cannot invoke arbitrary shell, filesystem, network, secret, deployment, or mutation operations.

## Completion and candidate output

When the model declares the task complete, the adapter returns exactly one candidate artifact conforming to `candidate.schema.json`. It must preserve the `change_set_id` returned by the successful `service.propose` call. No prose or unstructured explanation is added to the candidate JSON.

The trusted adapter records the provider's authoritative input/output token counts and inference cost, when available, as E-007 `model_usage` events. It does not write to the JSONL trace file directly. Instead, after each completed model response, it sends the gateway an internal NDJSON control message on the same trusted adapter-to-gateway pipe:

```json
{
  "type": "model_usage",
  "request_id": "generation-001",
  "input_tokens": 1234,
  "output_tokens": 87,
  "cost_usd": 0.0025
}
```

`cost_usd` is optional when the provider does not supply authoritative cost telemetry. Token counts are required, non-negative integers. The gateway writes this as an E-007 `model_usage` event using its run identity and host timestamp, and returns a `telemetry_ack` to the adapter. This control message is not a provider function/tool, is not included in the model-visible surface, and is never returned to the model. Only the trusted adapter may send it; model function calls are mapped exclusively to `agent.invoke` tool-call messages. A rejected acknowledgement is an adapter failure and the run cannot be scored as if telemetry were zero.

The gateway is the sole trace-file writer. This avoids concurrent appenders, out-of-order lines, and partially written JSONL records. Each provider response must use a unique `request_id` for its usage control message; duplicate IDs are rejected and cannot double-count tokens or cost. Trace timestamps use `time.monotonic_ns()`; the runner must use the same host monotonic clock for `agent_finished_at_ns`. The adapter must send the usage message before forwarding any tool call returned by that same model response, preserving the event's actual order. It must also send the final model response's usage event before marking the agent finished. It does not estimate missing telemetry. The run is marked incomplete when required usage data is unavailable; it is not silently assigned zero.

The adapter stops after the final candidate is received or the trial budget expires. It does not call the hidden evaluator and does not receive acceptance feedback during the run.

## Trace and finalization

- The gateway records each tool call, stable public failure code, named-schema lookup, and successful proposal hash. It never records proposal bodies or arbitrary tool arguments.
- The trusted adapter records model-usage events using the same run/task/attempt/candidate/model identity.
- The trusted outer runner records the agent-finished timestamp with the same host `time.monotonic_ns()` clock used by the gateway, then stores the candidate artifact.
- A separate trusted evaluator reads the candidate artifact read-only and evaluates it outside the model-visible boundary. Candidate data is untrusted JSON; the evaluator must not execute it.
- The evaluator writes only the coarse `evaluation-result.schema.json` result. It must set `eligible_for_acceptance` to false only for `PROVIDER_ERROR`, `ADAPTER_ERROR`, or `EVALUATOR_ERROR`; agent task failures, invalid candidates, and budget exhaustion remain eligible failures. Accepted outcomes are always eligible. Hidden assertion names, expected values, oracle data, and detailed mismatch diagnostics are not returned to the model.
- `finalize.py` correlates run identity, final artifact hash, and one identical proposal hash across successful `service.propose`, `service.validate`, and `service.plan` events; it also checks the full inspect/propose/validate/plan order and no-mutation/no-deploy plan flags. It then appends the authoritative `task_finished` event including `eligible_for_acceptance` and produces the E-007 summary. The summary retains all trials in `task_count`, reports infrastructure exclusions separately, and calculates acceptance rate only over eligible trials.
- The finalized trace and result are immutable experiment records. A failed or incomplete run is retained; it is never deleted or rerun under the same run ID.

## Arm equivalence requirements

An adapter is acceptable only when both arms use:
- the same provider endpoint and pinned model revision;
- the same system/task prompt and context policy;
- the same tool invocation mapping and gateway version;
- the same temperature, top-p, output limits, timeout, and retry policy;
- the same maximum tool-call, token, and wall-clock budgets;
- the same candidate output parsing and trace instrumentation.

The only permitted difference is whether non-discovery tool input schemas are included in the initial session surface or fetched by named calls to `interface.describe`.

Do not implement automatic retries at the adapter layer for rate limits, provider errors, or tool transport errors in one arm only. If provider retry behavior is unavoidable, make it identical, count it, and preserve the raw provider trace. Infrastructure failure must be classified separately from task failure.

## Failure classes

The runner must distinguish at least:
- provider transport/authentication/rate-limit failure;
- context or token budget exhaustion;
- wall-clock budget exhaustion;
- adapter protocol failure;
- gateway/tool diagnostic;
- candidate output absent or malformed;
- evaluator unavailable or invalid result;
- security/integrity violation.

Only the final three agent-side outcomes (accepted, ordinary task rejection, agent budget exhaustion) belong in task acceptance statistics. Provider outages and evaluator failures are infrastructure-invalid trials, retained in raw records but excluded from acceptance denominators under a predeclared rule. The exclusion rule must be applied symmetrically and reported with counts. Security/integrity violations invalidate the entire affected batch.

## Non-goals

The adapter contract does not select MCP, JSON-RPC, HTTP, a CLI, an SDK, or any other final Agent Native public protocol. It does not define a framework runtime, a general-purpose orchestration engine, or a production sandbox. It exists only to make one narrow experiment fair and auditable.
