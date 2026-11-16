# Agent Native

**An agent-first backend framework, engineered for production.**

> Built for agents. Engineered for production.

Agent Native explores a different premise for backend engineering: AI agents are the primary builders and operators of software, while humans define intent, policy, constraints, and acceptance criteria.

This is not an existing human-oriented framework with an AI plugin. The project starts by questioning the assumptions embedded in conventional backend frameworks, developer workflows, APIs, configuration, testing, deployment, and operations.

## Project status

**Research and foundation phase — no framework implementation has been selected or committed to yet.**

The repository is intentionally being built around evidence, explicit decisions, reproducible experiments, and measurable outcomes. Language, runtime, architecture, and initial scope remain open until the research and benchmark design justify them.

## What we are trying to improve

- The probability that an agent can take a backend task from intent to a correct, deployable result.
- The total cost of successful delivery: model tokens, tool calls, execution time, retries, infrastructure, and human intervention.
- Correctness, security, observability, operability, and maintainability of generated systems.
- Compatibility with agents of different capability levels and tool environments.
- The ability to inspect, verify, explain, repair, and safely evolve a running system.

## Core hypothesis

A backend framework designed around agent workflows can outperform conventional frameworks for agent-driven delivery if it makes system capabilities, constraints, state transitions, failure modes, and verification surfaces explicit and machine-actionable—without sacrificing production-grade runtime properties.

This is a hypothesis to test, not a claim of proven superiority.

## Design principles under evaluation

1. **Agent-native, not agent-exclusive:** optimize machine interaction while preserving understandable human interfaces and governance.
2. **Verifiable by construction:** provide deterministic checks and machine-readable evidence for generated changes and runtime behavior.
3. **Safe by default:** enforce permissions, isolation, validation, and policy in trusted runtime components, never by prompt instructions alone.
4. **Low-friction workflows:** reduce unnecessary context, tool calls, configuration ambiguity, and repair cycles.
5. **Production-first:** include migrations, observability, deployment, rollback, and operational contracts in the design.
6. **Progressive capability:** support simple agents through constrained workflows and advanced agents through composable interfaces.
7. **Interoperable:** investigate standards such as OpenAPI and MCP rather than creating proprietary protocols without evidence.
8. **Evidence over fashion:** choose languages, databases, protocols, and architecture from measured trade-offs.
9. **Incremental adoption:** investigate whether the framework can coexist with existing services and infrastructure.
10. **No hidden magic:** generated behavior, defaults, side effects, and resource costs must be inspectable.

## Research documents

- [Vision and problem statement](docs/vision.md)
- [Problem space and research questions](docs/problem-space.md)
- [Architecture principles and decision process](docs/architecture-principles.md)
- [Evaluation and benchmark strategy](docs/benchmark-strategy.md)
- [Roadmap and phase gates](docs/roadmap.md)

## Non-goals for the foundation phase

- Selecting a programming language because it is familiar or fashionable.
- Reimplementing Django, FastAPI, Rails, Spring, or another framework feature by feature.
- Assuming multi-agent orchestration is inherently better than a single agent.
- Treating generated code volume, benchmark scores, or token reduction alone as success.
- Building a large abstraction layer before validating a narrow end-to-end workflow.

## How decisions are made

Important choices must be recorded as Architecture Decision Records (ADRs), including context, alternatives, evidence, consequences, and a way to reverse or revisit the decision. See the roadmap for phase gates.

## Current phase

Research, problem definition, benchmark design, and architecture exploration. No production-readiness or performance claims are made at this stage.

## License

See [LICENSE](LICENSE).
