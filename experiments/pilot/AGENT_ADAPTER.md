# Pilot agent-adapter contract

**Status:** provider-neutral contract; no provider implementation is selected or included.

The adapter is the trusted bridge between a model-provider API and the local E-005 pilot gateway. It is not part of the Agent Native product and must not become a permanent framework abstraction merely because the pilot needs it.

## Trust boundary

The model provider receives only:
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

## Trial startup

1. The runner selects exactly one trial from a validated immutable schedule.
2. The runner creates a fresh E-005 gateway instance and a new exclusive trace file for that run.
3. The runner starts the gateway with its out-of-band run ID, candidate ID, model ID, task ID, and attempt number.
4. The adapter reads the gateway's first NDJSON message, which contains the session surface. It must not add or remove tool schemas.
5. The runner supplies the task text from `experiments/pilot/TASK.md`. It does not supply the pair ID, trial order, candidate label, hidden evaluator data, or schedule.
6. The adapter sends the prompt and session surface to the selected model using the exact generation settings pinned in the schedule.

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

The adapter must enforce the scheduled maximum tool-call count and wall-clock limit. The gateway additionally enforces its own request-size and tool allowlist. The model cannot invoke arbitrary shell, filesystem, network, secret, deployment, or mutation operations.

## Completion and candidate output

When the model declares the task complete, the adapter returns exactly one candidate artifact conforming to `candidate.schema.json`. It must preserve the `change_set_id` returned by the successful `service.propose` call. No prose or unstructured explanation is added to the candidate JSON.

The adapter records the provider's authoritative input/output token counts and inference cost, when available, as E-007 `model_usage` events. It does not estimate missing telemetry. The run is marked incomplete when required usage data is unavailable; it is not silently assigned zero.

The adapter stops after the final candidate is received or the trial budget expires. It does not call the hidden evaluator and does not receive acceptance feedback during the run.

## Trace and finalization

- The gateway records each tool call, stable public failure code, named-schema lookup, and successful proposal hash. It never records proposal bodies or arbitrary tool arguments.
- The trusted adapter records model-usage events using the same run/task/attempt/candidate/model identity.
- The trusted outer runner records the agent-finished timestamp and stores the candidate artifact.
- A separate trusted evaluator reads the candidate artifact read-only and evaluates it outside the model-visible boundary. Candidate data is untrusted JSON; the evaluator must not execute it.
- The evaluator writes only the coarse `evaluation-result.schema.json` result. It must set `eligible_for_acceptance` to false only for `PROVIDER_ERROR`, `ADAPTER_ERROR`, or `EVALUATOR_ERROR`; agent task failures, invalid candidates, and budget exhaustion remain eligible failures. Accepted outcomes are always eligible. Hidden assertion names, expected values, oracle data, and detailed mismatch diagnostics are not returned to the model.
- `finalize.py` correlates run identity, final artifact hash, successful proposal hash, inspect/propose/validate/plan sequence, and no-mutation/no-deploy plan flags. It then appends the authoritative `task_finished` event including `eligible_for_acceptance` and produces the E-007 summary. The summary retains all trials in `task_count`, reports infrastructure exclusions separately, and calculates acceptance rate only over eligible trials.
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
