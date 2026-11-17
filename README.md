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

Active research with E-001 through E-008 executable experiments and an E-009 integrated framework-kernel vertical slice. E-009 composes the E-001 service IR/parser, E-004 default-deny capability checks, tenant-scoped persistent storage, bounded HTTP host, durable jobs with lease/fencing and stop acknowledgements, transactional outbox/inbox delivery, durable SQLite authorization audit, and an Agent Gateway for inspect/propose/validate/plan with apply disabled. E-009 has 75 passing automated tests, including audit persistence/reopen/concurrency/fail-closed checks and a fail-closed plan guard. E-007 has one real-agent eval case, a Python runner, three deterministic scorers, and aggregate token/time budget controls. Its corrected three-run Qwen3 cohort failed 0/3 at validation with AN021: the model used a correct input array but omitted ir_version and existing operations from the full IR snapshot; all three used temperature 0/seed 42, so this is a deterministic failure reproduction, not statistical evidence. Post-fix real-model behavior is still open. E-005 schema and AN021 fix-hint tests and E-009 plan-gate tests pass in CI. E-002 has completed a ten-repetition shared-runner diagnostic matrix: all candidates passed functional HTTP checks but failed the provisional CPU screen, whose product-side provenance is not yet established. Ecosystem/fault-injection/artifact-size measurements remain open; no runtime is selected. No production framework, language, syntax, runtime, or public protocol has been selected.

## Canonical project contract

- `AGENTS.md` — agent execution and evidence rules.
- `VISION.md` — product mission and non-goals.
- `DESIGN_SPACE.md` — design dimensions and hypotheses.
- `EVALUATION.md` — benchmark protocol and decision gates.
- `DECISIONS.json` — machine-readable decision register.

All implementation work must satisfy these contracts. Research must converge into executable comparative experiments.


## Research report

See [REPORT.md](REPORT.md), [EVALUATION.md](EVALUATION.md), the RPI [research audit](research/research.md) and [execution plan](research/plan.md), plus the [peer-review checklist](research/peer-review-checklist.md). The [evidence index](research/evidence-index.md) links the E-002/E-007/E-009 artifacts; [design decisions](research/design-decisions.md) records key reversals and limitations. [E-009](experiments/e009/README.md) documents the integrated kernel and [IR contract](experiments/e009/ir-contract.md); [E-007](experiments/e007/README.md) documents the real-agent eval runner and failed Qwen3 cohort; [E-002](experiments/e002/decision-matrix.md) and its [CPU gate analysis](experiments/e002/cpu-gate-analysis.md) document the runtime diagnostic. The [future E-007 evaluation plan](research/e007-future-evaluation-plan.md) is proposed future work, not current evidence. The [agent-interface pilot guide](experiments/pilot/README.md) documents the separate progressive-disclosure experiment.
