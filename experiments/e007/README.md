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

`evals/e009-readonly-proposal.eval.json` defines one structured proposal task using the integrated E-009 Agent Gateway. `eval_runner.py` invokes the real `local_agent.py` Ollama adapter, preserves per-run traces/candidates, applies three deterministic scorers (candidate contract, proposal/validation/plan hash continuity, and behavioral safety), emits E-007 JSONL telemetry, and returns a non-zero exit if any repetition fails.

Run locally with the Qwen3-compatible Ollama template renderer:

```sh
sudo systemctl stop ollama.service 2>/dev/null || true
OLLAMA_GO_TEMPLATE=false OLLAMA_HOST=127.0.0.1:11434 ollama serve
# In another terminal:
ollama pull qwen3:8b
python experiments/e007/eval_runner.py --model qwen3:8b --arm upfront --repetitions 3
```

The GitHub workflow `.github/workflows/e007-real-agent-eval.yml` runs the same three-repetition Qwen3 trial when explicitly dispatched or when `experiments/e007/dispatch.json` changes. It is intentionally not part of ordinary PR CI or a deployment gate.

This is the first executable eval loop, not yet the full ten-task E-007 benchmark. Its trusted evaluator checks a fixed structured proposal; it does not execute arbitrary agent-generated code and is not a general-purpose sandbox or private oracle service. Three repetitions are a repeatability smoke check, not statistically strong evidence. No productivity or cost advantage is claimed.

The task manifest, workspace preparation, trace schema, metric aggregation, and first eval case are executable. The general isolated evaluator for arbitrary code tasks and the hidden E-007 oracle package remain unimplemented. For broader model comparisons, pin model IDs, tool policies, context limits, machine images, oracle versions, repetitions, and failure classification.
