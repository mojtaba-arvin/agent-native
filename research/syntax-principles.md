# Agent-Native Syntax: Design Constraints

This is a constraint set for experiments, not a language specification.

## Optimize for

1. Low ambiguity: every construct has one obvious interpretation.
2. Low concept count: common service tasks require few primitives.
3. Local completeness: an operation's inputs, outputs, effects, errors, authority, and resource limits are discoverable near its definition.
4. Mechanical validation: syntax and types enable cheap deterministic checks before runtime.
5. Repairable diagnostics: errors identify a stable code, source span, violated rule, and machine-actionable fix category.
6. Explicit effects: network, database, filesystem, secrets, time, randomness, process, and cross-service calls are visible in the contract.
7. Safe defaults: no ambient authority; resource bounds and deadlines are inherited or explicit.
8. Stable evolution: generated changes are local, diff-friendly, and compatible with versioned contracts.
9. Composable abstractions: agents reuse small verified building blocks rather than copy large patterns.
10. Readable traces: runtime events map back to source-level operations and causal context.

## Avoid

- syntax that requires memorizing punctuation-sensitive conventions;
- implicit imports, magic discovery, or runtime reflection for core correctness;
- overloaded names and context-dependent behavior;
- arbitrary metaprogramming as the default extension mechanism;
- hidden side effects;
- broad exception swallowing;
- implicit unbounded concurrency;
- non-local configuration precedence;
- generated code that becomes a second source of truth;
- syntax that is compact but hard to edit safely.

## Required syntax experiments

Prototype the same service in conventional imperative syntax, declarative resource/operation syntax, structured JSON-like IR, and hybrid declarations plus typed function bodies.

Evaluate completion, edit locality, syntax error rate, token cost, and how often the agent invents unsupported constructs. A syntax that is shorter but causes more repair loops loses.
