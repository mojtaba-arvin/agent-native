# Agent Native — Product Charter

## Thesis

Backend frameworks were shaped around human authors who read documentation, understand broad APIs, make local implementation choices, debug by inspection, and manually integrate infrastructure. AI agents have a different cost and failure profile: context is finite, tool calls are expensive, generated code is probabilistic, long action chains compound errors, and agents may not reliably infer implicit conventions.

A framework designed for agents should therefore change the programming model and runtime guarantees—not merely expose existing APIs through tools.

## Product

An independent backend framework for defining, building, testing, deploying, and operating distributed services. It owns the semantics that determine how a service is described, compiled or loaded, executed, secured, connected, persisted, observed, and evolved.

The product may include a dedicated language or syntax and a purpose-built runtime. The exact boundary is an empirical design decision.

## Primary users

AI coding and operating agents across capability levels:
- constrained agents with limited reasoning, context, and tool use;
- general agents that can plan and implement multi-step changes;
- advanced agents capable of architecture, optimization, and incident response.

The system must not require advanced agents to compensate for a confusing or unsafe framework.

## Success

Measure end-to-end accepted backend tasks, not lines of generated code or benchmark scores in isolation. A successful task must satisfy functional, security, reliability, performance, and operational acceptance criteria.

Optimize total cost per accepted task:
- model tokens and inference cost;
- tool calls and wall-clock time;
- retries, repair loops, and human intervention;
- runtime and infrastructure cost;
- failure, recovery, and maintenance cost.

## Required qualities

1. **Agent legibility:** few concepts, explicit semantics, compact canonical contracts, consistent patterns.
2. **Correctness by construction:** invalid states and unsafe effects rejected before execution where possible.
3. **Operational determinism:** observable, explainable lifecycle and failure behavior.
4. **Performance:** competitive latency, throughput, memory, startup, and resource efficiency.
5. **Distributed-systems competence:** service discovery, communication, retries, deadlines, consistency, idempotency, backpressure, and failure isolation.
6. **Security:** capability-based authority, isolation, explicit trust boundaries, secret handling, and auditable effects.
7. **Evolvability:** schema and API evolution, migrations, compatibility, rollback, and safe refactoring.
8. **Portability:** reproducible builds and deployment across practical environments.

## Non-goals

- A framework manager, wrapper, adapter, or code generator for existing backend frameworks.
- A prompt pack that asks agents to follow best practices.
- A collection of integrations without a coherent execution model.
- A syntax optimized only for human aesthetics.
- A toy language with no credible path to production workloads.
- A claim that all existing frameworks are inherently unsuitable for agents. That is a hypothesis to test fairly.

## Foundational principle

Treat the agent as the primary author, but treat the runtime as the authority. The agent proposes; trusted compilation and execution enforce.
