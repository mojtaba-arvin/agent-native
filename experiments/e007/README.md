# E-007 agent task corpus and trace metrics

Ten public task statements cover service contracts, schema evolution, tenant isolation, idempotency, deadlines/retries, streaming/backpressure, durable recovery, capability security, regression repair, and safe change planning.

**Oracle isolation:** acceptance oracles must be mounted by a separate evaluator outside the agent-visible workspace. This public corpus contains task prompts and oracle identifiers only; it intentionally does not include hidden assertions.

`trace.schema.json` defines a provider-neutral event envelope. `metrics.py` aggregates input/output tokens, tool calls, repair events, human interventions, inference cost, wall time, acceptance, and cost per accepted task. Run it with `python experiments/e007/metrics.py --input trace.jsonl --output summary.json`. Provider adapters must preserve raw traces and must not invent missing token or cost values.

Task-manifest and metric tests are executable. No agent runs have been performed, no hidden oracle package is included, and no productivity or cost advantage is claimed. Before model comparisons, pin model IDs, tool policies, context limits, machine images, oracle versions, repetitions, and failure classification.
