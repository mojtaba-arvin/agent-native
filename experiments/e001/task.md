# E-001 baseline task: Catalog service contract

This is the first representation-only task. It is intentionally not a complete backend implementation.

## Agent instruction

Define a service named `Catalog`, version `1`, with exactly two operations:

- `get_item`: GET `/items/{id}`; one `UUID` input named `id` sourced from the path; output type `Item`; effect `repository.read`; capability `items.read`.
- `create_item`: POST `/items`; one `String` input named `name` sourced from the body; output type `Item`; effect `repository.write`; capability `items.create`.

The candidate representation must declare the `Item` record, both operation contracts, validation rules, deterministic error sets, effects, and capabilities. It must be mechanically validated and normalized to the canonical shape in `schema/service-ir.schema.json`.

## Acceptance conditions

1. Service identity and version match exactly.
2. The `Item` record has exactly the declared typed fields.
3. Both operations exist exactly once with the specified contracts.
4. Validation rules and deterministic error sets match the task.
5. No undeclared type, field, operation, input, effect, or capability is present.
6. Invalid methods, non-absolute paths, duplicate names/fields, duplicate list entries, and unsupported input sources are rejected.
7. Canonical output is deterministic regardless of declaration order.
8. Diagnostics expose a stable code and source location.
9. A follow-up edit can add an optional query input to `get_item` without changing the existing contract.

## Comparison arms

- Text DSL: `examples/catalog.an`.
- Structured IR: `structured/catalog.ir.json`.
- Conventional language baselines: separately authored Go and Rust contracts/implementations, not generated from this prototype.

The fixtures are reference examples, not hidden acceptance tests. In an agent study, keep acceptance tests and expected outputs out of the agent-visible workspace.

## Data to collect

For every trial retain model and settings, prompt, tool policy, source revision, full interaction trace, input/output tokens, tool calls, elapsed time, edits, validation failures, repair loops, test outcome, and human intervention. Report failed and timed-out trials.
