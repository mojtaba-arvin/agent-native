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

Active research with E-001 through E-008 executable experiments and an E-009 integrated framework-kernel vertical slice. E-009 composes the E-001 service IR/parser, E-004 default-deny capability checks, tenant-scoped persistent storage, a bounded HTTP host, durable jobs with lease/fencing and stop acknowledgements, transactional outbox/inbox delivery, a durable SQLite authorization audit sink, and an Agent Gateway for inspect/propose/validate/plan with apply disabled. E-009 has 72 passing automated tests, including audit persistence/reopen/concurrency/fail-closed checks and bounded local-agent repair/provenance checks. Five standalone Qwen3 trials have been attempted; none has produced an accepted candidate, with the fifth reaching validation and failing on malformed IR. E-007 now has one real-agent eval case, a Python runner, and three deterministic scorers; its first three-run attempt exposed an Ollama template-renderer configuration issue, and the corrected three-run attempt is in progress. E-002 has completed a ten-repetition shared-runner diagnostic matrix: all candidates passed functional HTTP checks but failed the provisional CPU gate, so no runtime is selected. No production framework, language, syntax, runtime, or public protocol has been selected.

## Canonical project contract

- `AGENTS.md` — agent execution and evidence rules.
- `VISION.md` — product mission and non-goals.
- `DESIGN_SPACE.md` — design dimensions and hypotheses.
- `EVALUATION.md` — benchmark protocol and decision gates.
- `DECISIONS.json` — machine-readable decision register.

All implementation work must satisfy these contracts. Research must converge into executable comparative experiments.


## Research report

See [REPORT.md](REPORT.md) for current status and evidence boundaries, [EVALUATION.md](EVALUATION.md) for benchmark protocol and gates, and the RPI [research audit](research/research.md) and [execution plan](research/plan.md), plus the [RPI peer-review checklist](research/peer-review-checklist.md). [E-009](experiments/e009/README.md) demonstrates the integrated service/HTTP/security/data/jobs/agent-control path. [E-007](experiments/e007/README.md) documents the real-agent eval runner; [E-002](experiments/e002/decision-matrix.md) documents runtime screening criteria and current diagnostic results. The focused [agent-interface pilot guide](experiments/pilot/README.md) documents the separate progressive-disclosure experiment.
