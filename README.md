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

Active research with E-001 through E-008 executable experiments and an E-009 integrated framework-kernel vertical slice. E-009 composes the E-001 service IR/parser, E-004 default-deny capability checks, tenant-scoped persistent storage, bounded HTTP host, durable jobs with lease/fencing and stop acknowledgements, transactional outbox/inbox delivery, durable SQLite authorization audit, and an Agent Gateway for inspect/propose/validate/plan with apply disabled. E-009 has 80 passing automated tests. E-007 has one real-agent eval case, a Python runner, three deterministic scorers, aggregate token/time budget controls, and failure classification; its latest deterministic runner suite has 53 passing tests ([workflow 44188566011](https://github.com/mojtaba-arvin/agent-native/actions/runs/44188566011)). The first fixed-seed three-run Qwen3 cohort failed 0/3 with AN021. A later stochastic probe produced a complete-shaped IR but rewrote five existing operations. A deterministic post-Gateway run exhausted its input budget after inspecting five of six operations. The subsequent expanded-budget deterministic run ([workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970), [artifact](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970/artifacts/14360782135)) inspected all six operations and, after two bounded Gateway rejections, produced a third complete proposal accepted by the Gateway. Its IR preserved all existing operations exactly, contained the correct input array and ir_version=1, and caused no AN021. The run then reached its 1,800-second wall deadline while generating the next model response, before validation or plan. This is one deterministic proposal-level success, not a completed E-007 task or statistical evidence. E-002 has completed two ten-repetition shared-runner diagnostic matrices: all candidates passed functional HTTP checks but failed the provisional CPU screen, whose product-side provenance is not established. One Linux x86_64 uncompressed deployable payload per candidate has been measured. Ecosystem and comparable fault-injection measurements remain open; no runtime is selected. No production framework, language, syntax, runtime, or public protocol has been selected.

## Canonical project contract

- `AGENTS.md` — agent execution and evidence rules.
- `VISION.md` — product mission and non-goals.
- `DESIGN_SPACE.md` — design dimensions and hypotheses.
- `EVALUATION.md` — benchmark protocol and decision gates.
- `DECISIONS.json` — machine-readable decision register.

All implementation work must satisfy these contracts. Research must converge into executable comparative experiments.


## Research report

See [REPORT.md](REPORT.md), [EVALUATION.md](EVALUATION.md), the RPI [research audit](research/research.md) and [execution plan](research/plan.md), plus the [peer-review checklist](research/peer-review-checklist.md). The [evidence index](research/evidence-index.md) links the E-002/E-007/E-009 artifacts; [design decisions](research/design-decisions.md) records key reversals and limitations. [E-009](experiments/e009/README.md) documents the integrated kernel and [IR contract](experiments/e009/ir-contract.md); [E-007](experiments/e007/README.md) documents the real-agent eval runner and failed Qwen3 cohort; [E-002](experiments/e002/decision-matrix.md) and its [CPU gate analysis](experiments/e002/cpu-gate-analysis.md) document the runtime diagnostic. The [future E-007 evaluation plan](research/e007-future-evaluation-plan.md) is proposed future work, not current evidence. The [expanded-budget proposal trace analysis](experiments/e007/results/2026-11-17-expanded-budget-proposal-accepted-timeout.md) records the latest real-model partial success and wall-time limitation. The [agent-interface pilot guide](experiments/pilot/README.md) documents the separate progressive-disclosure experiment.

Evidence and current decisions are indexed in [research/evidence-index.md](research/evidence-index.md) and [research/design-decisions.md](research/design-decisions.md). The second-pass E-002 payload results are [documented here](experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md).
