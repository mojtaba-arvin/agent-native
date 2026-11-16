# Architecture Principles and Decision Process

## Architecture is not selected yet

This project deliberately does not prescribe a language, runtime, database, transport, or application architecture in the foundation phase. Those choices must follow comparative research and benchmark evidence.

## Principles

### A. Separate agent interface from runtime trust

The agent-facing surface may be convenient and expressive, but it must not be the security boundary. Authorization, validation, isolation, quotas, and audit must be enforced by trusted runtime components.

### B. Make capabilities explicit

Every exposed operation should have:
- A stable identifier and version.
- A machine-readable input and output schema.
- Preconditions and postconditions.
- Declared side effects.
- Required capabilities and scopes.
- Timeouts, retry semantics, and idempotency behavior where relevant.
- Structured error types.
- Examples and executable conformance tests.

### C. Prefer bounded workflows over unrestricted magic

High-level operations should make common tasks easy to discover and execute. Lower-level escape hatches may exist, but their risks and effects must be explicit.

### D. Verification is part of the product

The framework should expose consistent ways to validate configuration, contracts, migrations, security policy, application behavior, and deployability. A successful command must mean something precise.

### E. Preserve inspectability

Generated artifacts must be reviewable, versionable, reproducible, and operable without requiring a proprietary agent runtime.

### F. Design for interruption and recovery

Long-running operations need explicit states, checkpoints where useful, safe retries, cancellation, and recovery semantics. Do not introduce distributed orchestration unless measured requirements justify it.

### G. Use standards selectively

Evaluate OpenAPI, JSON Schema, MCP, AsyncAPI, OCI images, OpenTelemetry, and established database migration conventions. Adopt standards where they solve real interoperability problems; do not turn the framework into a pile of protocols.

### H. Keep the core small

A small trusted core with optional adapters is preferable to a large mandatory dependency graph, provided it does not push essential complexity onto every application.

### I. Optimize total delivery cost

Measure model tokens, tool calls, wall-clock time, retries, human intervention, infrastructure cost, and quality. A local optimization is not accepted if it worsens total cost or reliability.

### J. Avoid model-specific assumptions

The framework should not depend on hidden reasoning behavior, proprietary prompt formats, or a single model vendor. Agent integrations should use documented interfaces and conformance tests.

## Decision record requirements

Every significant architecture decision must be documented under docs/adr/ using this structure:

1. **Status:** proposed, accepted, superseded, or rejected.
2. **Context:** problem and constraints.
3. **Decision drivers:** measurable priorities.
4. **Options considered:** realistic alternatives, including doing nothing.
5. **Evidence:** documentation, experiments, benchmarks, and known limitations.
6. **Decision:** the selected option and scope.
7. **Consequences:** benefits, costs, risks, and operational impact.
8. **Revisit triggers:** evidence that would justify changing the decision.

## Initial decision register

| Decision | Status | Required evidence |
|---|---|---|
| Primary implementation language | Open | Agent task benchmark, ecosystem, runtime and maintenance trade-offs |
| Application language strategy | Open | Single-language vs multi-language experiment |
| Runtime and execution model | Open | Concurrency, isolation, startup, throughput and operational tests |
| Application specification | Open | Agent comprehension and change-task experiments |
| Agent-facing interface | Open | CLI/API/MCP comparison and usability across agent capability tiers |
| Persistence and migrations | Open | Correctness, recovery, portability and operational comparison |
| Security model | Open | Threat model, permission tests and adversarial evaluation |
| Deployment model | Open | Reproducibility, portability and rollback tests |

## Architectural anti-patterns to avoid

- A prompt file masquerading as a security policy.
- Requiring an LLM for deterministic framework operations.
- Exposing every internal function as an agent tool.
- Requiring agents to memorize undocumented conventions.
- Building a universal abstraction before validating at least two real use cases.
- Treating generated code as disposable or exempt from maintenance.
- Treating successful compilation as proof of correctness.
- Making a database, queue, model provider, or cloud platform mandatory without evidence.
- Introducing multiple agents where a deterministic workflow is cheaper and safer.
