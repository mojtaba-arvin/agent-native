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

Active first-principles experiments E-001 through E-010, plus an E-011 inter-service research plan. The experiments are evidence instruments, not a preselected implementation stack.

- **E-001–E-004:** executable contract/IR prototypes, runtime-substrate baselines, task execution semantics, and a default-deny capability reference model.
- **E-005–E-006:** agent-facing inspect/propose/validate/plan interface and durable execution semantics, including idempotency, leases, fencing, and cancellation boundaries.
- **E-007:** real-agent evaluation infrastructure plus a corrected 2×2 proposal-surface factorial. Snapshot/delta representation is crossed with per-operation/upfront-full contract delivery; minimal-disclosure delta is a separate exploratory treatment. Gateway, local-agent adapter, independent trusted-base evaluator, A–E case manifests, and a fail-closed manual-only dispatch path are implemented. Deterministic CI passes. The new factorial has **not** been run against a real model. Historical Qwen3 trials include validation failures, contract-preservation drift, an accepted proposal without completed validation/plan, and an ineligible Second Light run; none establishes end-to-end task acceptance.
- **E-008:** transactional outbox/inbox reference model demonstrating at-least-once delivery with idempotent consumer processing; no arbitrary external API exactly-once guarantee.
- **E-009:** integrated framework-kernel vertical slice composing the service IR/parser, capability checks, tenant-scoped storage, bounded HTTP host, durable jobs, outbox/inbox delivery, audit, and Agent Gateway. The default Gateway supports inspect/propose/validate/plan and keeps apply disabled.
- **E-010:** isolated sandbox-apply demonstration using a private temporary SQLite store and an explicitly injected coordinator. It is not a production mutation or deployment path.
- **E-011:** [research plan](research/e011-interservice-communication-plan.md) for inter-service invocation and distributed failure semantics. It distinguishes service RPC, agent-tool protocols, agent-to-agent collaboration, event delivery, and orchestration layers. It is gated on E-007 real-agent acceptance and E-010 sandbox-apply review; no transport is selected.

The historical E-002 Go/Rust/WASI/BEAM probes remain diagnostic; no runtime has been selected. No product language, syntax, runtime, service protocol, or persistence substrate has been selected. The next E-007 step is a manually dispatched, no-apply matched pilot using unchanged Qwen3 settings; branch pushes cannot start that model workflow.

## Canonical project contract

- `AGENTS.md` — agent execution and evidence rules.
- `VISION.md` — product mission and non-goals.
- `DESIGN_SPACE.md` — design dimensions and hypotheses.
- `EVALUATION.md` — benchmark protocol and decision gates.
- `DECISIONS.json` — machine-readable decision register.

All implementation work must satisfy these contracts. Research must converge into executable comparative experiments.


## Research report

See [REPORT.md](REPORT.md), [EVALUATION.md](EVALUATION.md), the RPI [research audit](research/research.md) and [execution plan](research/plan.md), plus the [peer-review checklist](research/peer-review-checklist.md). The [evidence index](research/evidence-index.md) links the E-002/E-007/E-009 artifacts; [design decisions](research/design-decisions.md) records key reversals and limitations. [E-009](experiments/e009/README.md) documents the integrated kernel and [IR contract](experiments/e009/ir-contract.md); [E-007](experiments/e007/README.md) documents the real-agent eval runner and failed Qwen3 cohort; [E-002](experiments/e002/decision-matrix.md) and its [CPU gate analysis](experiments/e002/cpu-gate-analysis.md) document the runtime diagnostic. The [future E-007 evaluation plan](research/e007-future-evaluation-plan.md) is proposed future work, not current evidence. The [17 November expanded-budget trace analysis](experiments/e007/results/2026-11-17-expanded-budget-proposal-accepted-timeout.md) records an earlier real-model partial proposal acceptance without validation/plan; the [18 November Second Light trace analysis](experiments/e007/results/2026-11-18-second-light-trace-analysis.md) records the subsequent ineligible retry. The [agent-interface pilot guide](experiments/pilot/README.md) documents the separate progressive-disclosure experiment.

Evidence and current decisions are indexed in [research/evidence-index.md](research/evidence-index.md) and [research/design-decisions.md](research/design-decisions.md). The second-pass E-002 payload results are [documented here](experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md).
