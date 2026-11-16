# E-007 agent task corpus and trace metrics

Ten public task statements cover service contracts, schema evolution, tenant isolation, idempotency, deadlines/retries, streaming/backpressure, durable recovery, capability security, regression repair, and safe change planning.

**Oracle isolation:** acceptance oracles must be mounted by a separate evaluator outside the agent-visible workspace. This public corpus contains task prompts and oracle identifiers only; it intentionally does not include hidden assertions. See [ORACLE_ISOLATION.md](ORACLE_ISOLATION.md) for the required trust boundaries.

`prepare_workspace.py` materializes exactly one public task into a minimal agent-visible workspace and excludes oracle identifiers and other task prompts. It does not run an agent or provide a sandbox.

`trace.schema.json` defines a provider-neutral trace event envelope. For comparative trials, events should include a stable `run_id`, `candidate_id`, and `model_id`. All events for one candidate/task execution share the same `run_id`; the aggregator groups by `run_id`, `task_id`, and `attempt`. This prevents repeated runs or different candidate arms from being merged into one result. These identity fields remain optional for older traces; legacy traces are grouped by task and attempt.

`metrics.py` aggregates input/output tokens, tool calls, repair events, human interventions, inference cost, wall time, acceptance, runtime metrics, and cost per accepted task. Run it with:

```sh
python experiments/e007/metrics.py --input trace.jsonl --output summary.json
```

Provider adapters must preserve raw traces and must not invent missing token or cost values. Missing telemetry is reported as incomplete, not silently converted to zero. Candidate and model labels are carried into each per-run task result; compare candidates using those labels rather than pooling all runs.

The task manifest, workspace preparation, and metric aggregation tests are executable. No agent runs have been performed, no hidden oracle package is included, and no productivity or cost advantage is claimed. Before model comparisons, pin model IDs, tool policies, context limits, machine images, oracle versions, repetitions, and failure classification.
