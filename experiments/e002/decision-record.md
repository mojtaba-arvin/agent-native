# E-002 final provisional product-scenario decision

**Date:** 18 November 2026  
**Selected scenario:** agent/tool-execution control plane  
**Runtime:** none selected

## Why this scenario

Agent Native's runtime substrate serves the control-plane boundary: authenticated HTTP, Gateway dispatch, schema/contract validation, authorization, durable audit, and bounded work submission. Model inference is excluded because it runs in the model provider and should not be attributed to the local HTTP runtime.

## Provisional capacity envelope

This is a registered hypothesis for the next product-representative measurement, not an observed production SLO:

| Dimension | Provisional target |
|---|---:|
| Replica size | 1 vCPU |
| Sustained successful control-plane throughput | 100 req/s |
| Concurrency | 32 |
| p99 control-plane latency | ≤ 100 ms |
| Sustained CPU utilization | ≤ 50% of one vCPU |
| CPU budget implied by capacity | ≤ 25 CPU-s / 5,000 requests |
| Authorization / tenant / audit / data-integrity violations | 0 |
| Registered fault-injection assertions | 100% pass |

At 100 requests/s, 50% of one vCPU provides 0.005 CPU-seconds per request, or 25 CPU-seconds per 5,000 requests. This replaces the old 0.5 CPU-seconds/5,000 experimental screen as a future hard gate. The old value had no documented product-capacity derivation. Historical results are retained as measured and are not rescored under the new hypothesis.

## Runtime decision: none

No Go, Rust, WASI P2, or BEAM runtime is selected. Current evidence uses a trivial in-memory `GET /work?ms=0` endpoint on shared GitHub-hosted runners. It does not exercise the selected product scenario's authenticated dispatch, authorization, durable audit, queue/outbox, or tool-execution path. The ecosystem/operability rubric and comparable fault-injection semantics suite also remain unmeasured. WASI P2's host-owned HTTP boundary is not yet operationally equivalent to the native listener candidates.

The next decision-grade comparison must run the selected control-plane workload on a controlled host, include the registered failure semantics, and retain raw request-level data. The current benchmark does not justify choosing or eliminating any candidate.
