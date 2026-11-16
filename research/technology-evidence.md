# Technology Evidence — Initial Scan

Status: exploratory evidence, not a selection. Snapshot: 2026-11-16.

## WebAssembly Component Model / WASI

**Observed:** WASI 0.3 was ratified in June 2026. Its component model exposes native asynchronous functions, futures, and streams across component boundaries. Wasmtime 46+ implements WASI 0.3 async primitives and can serve HTTP components. The Component Model is still being developed incrementally; upstream describes releases as Developer Preview milestones.

**Implication:** WASM components deserve a serious runtime/substrate experiment because typed interfaces, capability-oriented imports, composability, and async across component boundaries align with isolation and agent-authored service boundaries. This is not evidence that WASM is best: performance, database/network integration, observability, debugging, toolchain maturity, and operational complexity must be measured.

Sources:
- https://github.com/WebAssembly/WASI/blob/main/docs/ComponentModelFeatures.md
- https://github.com/WebAssembly/component-model
- https://component-model.bytecodealliance.org/reference/faq.html
- https://component-model.bytecodealliance.org/design/async.html
- https://component-model.bytecodealliance.org/running-components/wasmtime.html

## Rust / Tokio

**Observed:** Tokio exposes a multi-thread scheduler with work stealing and a current-thread scheduler. Its runtime combines task scheduling, I/O driving, and timers.

**Implication:** Rust plus Tokio is a strong baseline for a native, high-control runtime. It demonstrates that user-facing framework concepts can hide runtime complexity while preserving execution semantics. Agent ergonomics must be measured separately from runtime quality.

Sources:
- https://docs.rs/tokio/latest/tokio/runtime/
- https://docs.rs/tokio/latest/tokio/runtime/index.html

## Go runtime

**Observed:** Go multiplexes goroutines over OS threads using G/M/P scheduler resources. Its official documentation describes lightweight goroutines, stack growth, preemption, and scheduler trade-offs.

**Implication:** Go is a strong baseline for simple concurrent service execution and low operational complexity. Its implicit runtime behavior should be compared against an explicit effect/concurrency model designed for agent-generated programs.

Sources:
- https://go.dev/doc/faq
- https://go.dev/src/runtime/HACKING
- https://go.dev/doc/diagnostics
- https://go.dev/blog/container-aware-gomaxprocs

## Zig

**Observed:** Zig 0.15.1 removed language-level async/await keywords and describes async-related machinery as evolving around low-level primitives and standard-library I/O interfaces. Historical Zig documentation contains a materially different async model.

**Implication:** Zig remains a candidate for low-level runtime implementation, but its current async/I/O direction and ecosystem maturity need direct investigation. Old tutorials are not reliable evidence for current design.

Sources:
- https://ziglang.org/download/0.15.1/release-notes.html
- https://ziglang.org/documentation/0.15.1/

## Gleam / BEAM

**Observed:** Gleam combines a static type system with the Erlang runtime on its Erlang target. Its documentation lists support for recent OTP versions. Gleam's FAQ notes that typed message passing is provided by libraries rather than the language core. BEAM processes and preemptive scheduling provide a mature actor/concurrency model.

**Implication:** Gleam/BEAM is a useful baseline for fault isolation, actor semantics, and typed syntax. Questions include external ecosystem integration, runtime footprint, database/network performance, and whether existing language constraints provide enough control.

Sources:
- https://gleam.run/documentation/compatibility-reference/
- https://gleam.run/frequently-asked-questions/
- https://gleam.run/

## Benchmark integrity

**Observed:** Recent analysis of SWE-Bench Pro reports that reward hacking and task-quality problems can distort agent benchmark outcomes.

**Implication:** Agent Native's benchmark must own task quality, hidden tests, environment control, and anti-cheating checks. Public score comparisons alone are insufficient.

Source:
- https://arxiv.org/abs/2609.08149

## Current hypotheses (not decisions)

1. A typed canonical IR may be more robust than making textual DSL the only source of truth.
2. A purpose-built service language may reduce agent ambiguity, but only if it beats idiomatic existing-language baselines on task success and total cost.
3. WASM Component Model is a promising isolation and component ABI candidate; a native runtime may still win on latency, throughput, and operational simplicity.
4. Runtime concurrency and failure semantics should be first-class framework concepts rather than ad hoc library choices.
5. Implementation language and service-definition language are independent decisions and must be benchmarked separately.

## Missing evidence

- Current official toolchain versions pinned to experiment images.
- Native-vs-WASM performance on identical HTTP/database/event workloads.
- Agent success rates and token/tool cost for equivalent tasks in Go, Rust, Gleam, and a prototype DSL.
- Runtime memory behavior and tail latency under load, failure, and tenant isolation.
- A credible design for durable workflows, transactions, and schema evolution.
