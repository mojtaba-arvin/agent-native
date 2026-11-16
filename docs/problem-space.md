# Problem Space and Research Questions

This document defines the problem areas to investigate before selecting an implementation architecture.

## 1. Intent and specification

**Problem:** Natural-language requirements are ambiguous, incomplete, and often omit non-functional constraints.

Research questions:
- What should the canonical application specification contain?
- Can requirements, invariants, authorization rules, data contracts, and acceptance tests share a typed representation?
- How should ambiguity and conflicting requirements be surfaced?
- Which decisions require human approval?
- How can the specification evolve without silently changing behavior?

Candidate directions: typed manifests, schema-first contracts, executable specifications, invariant declarations, generated acceptance tests.

## 2. Discovery and context

**Problem:** Agents spend context and tool calls discovering project conventions, dependencies, architecture, and available operations.

Research questions:
- What is the smallest useful project map?
- Which metadata should be generated and kept current?
- Can capabilities be queried by task rather than exposing the entire framework surface?
- How should large projects be summarized without losing correctness-critical details?
- How can the framework detect stale or contradictory project metadata?

Candidate directions: machine-readable project index, capability registry, dependency graph, generated context packs, semantic diagnostics.

## 3. Application construction

**Problem:** Agents must coordinate routes, schemas, persistence, authorization, background jobs, configuration, and deployment.

Research questions:
- Which constructs should be declarative and which should remain ordinary code?
- Can common backend changes be expressed as atomic, typed operations?
- How should generated code remain editable and understandable?
- What is the minimum stable abstraction set?
- Can the framework support multiple application languages or runtimes without creating an expensive lowest-common-denominator abstraction?

Candidate directions: declarative application model, typed resource definitions, explicit lifecycle hooks, generated adapters, code-first escape hatches.

## 4. Data and state

**Problem:** Data models, migrations, transactions, consistency, and concurrency are difficult to change safely.

Research questions:
- How are schema changes planned, previewed, applied, and rolled back?
- How are destructive operations identified and gated?
- How are invariants and authorization enforced below the application layer?
- What state must survive agent interruption or process restart?
- How should idempotency, retries, and concurrency be represented?

Candidate directions: migration plans, schema diffs, invariant checks, transaction boundaries, idempotency keys, resumable execution.

## 5. Verification and debugging

**Problem:** Agents may produce code that looks correct but fails at integration, runtime, security, or operational boundaries.

Research questions:
- What verification levels are mandatory before a change is accepted?
- Can diagnostics include structured cause, location, violated contract, and remediation hints?
- How can tests be selected without omitting relevant regression coverage?
- How do we prove that a generated migration or API change preserves invariants?
- How should the system distinguish a failed test from an unavailable dependency or broken environment?

Candidate directions: deterministic validators, generated contract tests, integration harnesses, static analysis, runtime probes, structured error taxonomy.

## 6. Security and governance

**Problem:** Agent-generated code and agent-operated tools create risks around permissions, secrets, data access, command execution, and deployment.

Research questions:
- What is the trust boundary between agent, framework, application, and infrastructure?
- How are capabilities granted, scoped, revoked, and audited?
- Which operations require approval or dual control?
- How are secrets kept out of model context and logs?
- How are generated code and dependencies assessed?
- How do we prevent prompt injection from becoming an authorization bypass?

Candidate directions: capability-based permissions, policy enforcement in trusted code, sandboxing, secret brokers, immutable audit events, approval gates.

## 7. Operations and deployment

**Problem:** A working local endpoint is not a production service.

Research questions:
- What constitutes a deployable artifact?
- How are health, readiness, shutdown, configuration, and resource limits standardized?
- How are observability and operational runbooks generated?
- How are deployments, migrations, rollback, and recovery coordinated?
- What infrastructure assumptions are unavoidable?

Candidate directions: reproducible builds, deployment plans, health contracts, telemetry conventions, staged rollout, rollback plans.

## 8. Cost and performance

**Problem:** Agent productivity can be offset by token consumption, repeated tool calls, slow test cycles, runtime overhead, and infrastructure complexity.

Research questions:
- What is the total cost per accepted task?
- Which framework features reduce agent cost and which increase it?
- How should context, tool output, and diagnostics be bounded?
- What is the acceptable runtime and memory overhead?
- Which work should be cached, parallelized, or delegated?

Candidate directions: compact schemas, incremental validation, deterministic caching, local-first workflows, cost attribution, resource budgets.

## 9. Capability-adaptive interaction

**Problem:** Agents vary in planning ability, context size, tool reliability, and coding skill.

Research questions:
- What is the minimum capability contract an agent must satisfy?
- Can workflows expose a simple safe path and an advanced composable path?
- How can the framework detect when an agent needs a smaller task or stronger guardrails?
- Can the same task be completed through CLI, API, MCP, or ordinary files?
- How can we prevent a complex agent interface from overwhelming weaker agents?

Candidate directions: progressive disclosure, task-oriented commands, explicit state machines, schema validation, bounded plans, human escalation.

## 10. Ecosystem and interoperability

**Problem:** A new framework must integrate with existing languages, databases, queues, identity systems, deployment platforms, and agent tools.

Research questions:
- Which existing protocols should be adopted rather than reinvented?
- Is MCP appropriate for capability discovery and tool execution, or only as an adapter?
- What role should OpenAPI and AsyncAPI play?
- How can the framework avoid coupling application semantics to a single model vendor?
- What is the migration path from existing backend systems?

Candidate directions: protocol adapters, stable contracts, provider-neutral interfaces, compatibility layers, import/export tooling.

## Required output of this research phase

Before committing to a framework architecture, produce:
1. A comparative analysis of existing backend frameworks and agent development tools.
2. A prioritized problem list supported by benchmark results, documented issues, or reproducible experiments.
3. A proposed minimum viable end-to-end workflow.
4. A benchmark harness and baseline results.
5. Architecture Decision Records for language, runtime, application model, agent interface, persistence, and deployment.
