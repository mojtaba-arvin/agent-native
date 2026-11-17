# Agent Native

**A new backend framework built for AI agents, not human programmers.**

Agent Native is intended to be the framework itself: its own programming model, language or syntax, runtime, service lifecycle, standard library, and distributed-systems semantics. It is not a wrapper around FastAPI, Django, Go frameworks, or any existing backend framework.

The central question is not how to make today's frameworks easier for agents to use. It is:

> If AI agents are the primary authors and operators of backend systems, what should a backend framework become when designed from first principles for them?

## Product objective

Enable agents from weak to strong to build and operate reliable, secure, high-performance microservice systems while minimizing:
- agent reasoning and tool-call burden;
- generated code volume and ambiguity;
- debugging and repair loops;
- runtime, infrastructure, and operational cost;
- security and correctness failures;
- long-term change and maintenance cost.

## Design freedom

The project may create a purpose-built language, DSL, compiler, virtual machine, native runtime, service protocol, or a hybrid. No implementation language or existing framework is preselected.

## Current status

Active research with E-001 through E-008 executable experiments and an E-009 integrated framework-kernel vertical slice. E-009 composes the E-001 service IR/parser, E-004 default-deny capability checks, tenant-scoped persistent storage, a bounded HTTP host, durable jobs with lease/fencing and stop acknowledgements, transactional outbox/inbox delivery, and an Agent Gateway for inspect/propose/validate/plan with apply disabled. E-009 has 63 passing automated tests in its latest verified CI run, including a bounded local Ollama runner and independent candidate-preservation/no-apply checks. The separate E-005 disclosure pilot has a local-only Ollama runner and paired analysis harness. E-009 now also has a bounded local Ollama runner for the integrated kernel; neither has a recorded real-model run or evaluator-backed acceptance result yet. E-002 smoke matrices remain non-decision-grade. No production framework, language, syntax, runtime, or public protocol has been selected.

## Canonical project contract

- `AGENTS.md` — agent execution and evidence rules.
- `VISION.md` — product mission and non-goals.
- `DESIGN_SPACE.md` — design dimensions and hypotheses.
- `EVALUATION.md` — benchmark protocol and decision gates.
- `DECISIONS.json` — machine-readable decision register.

All implementation work must satisfy these contracts. Research must converge into executable comparative experiments.


## Research report

See [REPORT.md](REPORT.md) for the current research status, completed experiments, evidence boundaries, evaluation gates, and next milestones. [E-009](experiments/e009/README.md) demonstrates the integrated service/HTTP/security/data/jobs/agent-control path. The focused [agent-interface pilot guide](experiments/pilot/README.md) documents the separate progressive-disclosure experiment.
