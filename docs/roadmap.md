# Roadmap and Phase Gates

This roadmap is evidence-driven. Dates are intentionally not promised before task scope and access to reproducible environments are known.

## Phase 0 — Repository and research foundation

**Goal:** establish project principles, research questions, decision process, and scope.

Deliverables:
- Vision and problem statement.
- Problem-space map.
- Architecture principles and decision register.
- Benchmark strategy.
- Research source catalogue.
- Contribution and documentation conventions.

Exit gate:
- No unresolved contradiction in the project thesis.
- Research questions are prioritized.
- Architecture choices remain explicitly open where evidence is insufficient.

## Phase 1 — Comparative research and baseline

**Goal:** understand existing solutions and quantify where agent-driven backend delivery fails.

Investigate:
- Django, FastAPI, Flask, Rails, Laravel, NestJS, Spring Boot, ASP.NET Core, and selected Go ecosystems.
- Agent-oriented coding environments and their tool interfaces.
- Schema-first and contract-first approaches.
- Build/test/deploy tooling and security models.
- Existing backend and repository-level agent benchmarks.

Deliverables:
- Feature and workflow comparison matrix.
- Agent friction taxonomy backed by reproducible observations.
- Candidate use cases and non-goals.
- A small benchmark task set and baseline results.
- Initial threat model.

Exit gate:
- A specific, defensible problem is identified that current alternatives do not adequately solve.
- At least one narrow end-to-end workflow is selected for a prototype.
- The proposed value can be measured against existing frameworks.

## Phase 2 — Architecture experiments

**Goal:** test competing design choices before committing to a core.

Experiments:
- Language and runtime candidates.
- Declarative specification versus code-first interfaces.
- CLI, API, and MCP-based agent interaction.
- Generated code versus runtime interpretation.
- Verification and diagnostics designs.
- Security boundaries and capability enforcement.
- Single-process versus distributed execution where justified.

Deliverables:
- Reproducible experiment results.
- Architecture Decision Records.
- Threat model and security requirements.
- Prototype interface contracts.

Exit gate:
- Decisions are supported by measured trade-offs.
- The smallest coherent architecture can support the chosen use case.

## Phase 3 — Vertical-slice prototype

**Goal:** deliver one complete backend workflow, not a collection of disconnected abstractions.

The prototype must allow an agent to:
1. Understand a bounded requirement and project state.
2. Create or modify a service.
3. Define an API and persistence behavior.
4. Apply a safe migration.
5. Run deterministic verification.
6. Diagnose and repair a seeded failure.
7. Produce a reproducible deployable artifact.
8. Report evidence, limitations, and operational instructions.

Exit gate:
- Acceptance, regression, security, and deployment checks pass.
- Results are compared with conventional framework baselines.
- Known limitations are documented.

## Phase 4 — Reliability and capability adaptation

**Goal:** improve results across different agent capability tiers.

Focus:
- Progressive disclosure and simpler task interfaces.
- Structured diagnostics and recovery.
- Interruption and resumability.
- Context and token efficiency.
- Security and adversarial testing.
- Compatibility and upgrade behavior.

Exit gate:
- Repeated benchmark runs show material improvement without unacceptable runtime or security regressions.

## Phase 5 — Production hardening

**Goal:** establish operational credibility.

Focus:
- Performance and resource profiling.
- Observability, backup, restore, and rollback.
- Dependency and supply-chain security.
- Compatibility policy and release engineering.
- Documentation and migration guidance.
- Independent review and reproducible builds.

Exit gate:
- Explicit production-readiness criteria are met; no maturity label is assigned by aspiration alone.

## Phase 6 — Ecosystem and broader language support

**Goal:** expand only after the core workflow is validated.

Potential work:
- Additional language/runtime adapters.
- Database, queue, identity, and cloud integrations.
- Agent protocol adapters.
- Migration tools for existing applications.
- Plugin and extension model.

## Current priorities

1. Finish Phase 0 and establish a source-backed research register.
2. Complete Phase 1 comparative research.
3. Build the first reproducible benchmark before selecting the implementation language.
4. Record decisions as ADRs.
5. Prototype one vertical slice only after the baseline exists.

## Scope discipline

Do not begin a broad framework implementation, promise multi-language support, or publish performance claims before the relevant phase gates are satisfied.
