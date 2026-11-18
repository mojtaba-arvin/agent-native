# E-002 — Product benchmark gap analysis and decision gate

**Review date:** 2026-11-18  
**Status:** decision record; no runtime or storage winner.

## Decision

Do not rank or select Go, Rust, WASI P2, or BEAM from the current E-002 measurements. Retain all four candidates. The current executable black-box contract and load runner exercise a deliberately small HTTP server (/health, /work, /stream) and do not exercise the proposed Agent Native control-plane lifecycle. The product workload specification is materially different: authentication, trusted tenant resolution, contract validation, default-deny authorization, validate/plan, durable job admission, outbox, idempotency, and audit.

The current matrix runner is a valid harness for its toy workload, not a product benchmark. The workflow's benchmark-matrix job has been skipped in recent ordinary CI; candidate build and conformance success is not a capacity result. Short 100-request sampler smokes are instrumentation checks only.

## Evidence classification

| Evidence | What it proves | What it does not prove |
|---|---|---|
| Rust/Go/BEAM/WASI build and unit tests | Candidate source builds and its own tests pass | Cross-runtime product equivalence |
| E-002 /work black-box conformance | HTTP status/body, deadline, query parsing, streaming behavior for the toy endpoint | Agent Native lifecycle or persistence semantics |
| 100-request process-tree sampler smoke | Sampler runs and reports plausible metadata on a short trial | Stable CPU accounting, cgroup totals, or throughput ranking |
| 5,000-request / 10-repetition matrix design | A randomized repeated harness exists | Product relevance until workload and all candidate implementations are equivalent |
| E-002 storage contract v1 | Shared durability semantics and fault cases are specified | Any adapter currently satisfies them |

## Blocking gaps before a valid product comparison

1. **Workload parity:** all candidates must implement the same lifecycle and request mix from control-plane-workload.md; no candidate-specific shortcuts.
2. **Trusted identity:** the harness must inject authenticated principal/tenant context outside client-controlled payloads.
3. **Atomic admission:** job, outbox event, idempotency result, and canonical admission audit record must commit as one durable transaction.
4. **Audit semantics:** replay and denied attempts require separate durable audit events without duplicate logical admission.
5. **Failure correctness:** deterministic injection around commit/response, audit outage, queue saturation, restart, duplicate delivery, and worker recovery.
6. **Durability parity:** adapters must pass storage-conformance-contract.md under an explicitly recorded local durable-commit profile.
7. **Controlled resources:** one-vCPU isolated runner/cgroup v2; record cpu.max, cpu.stat, throttling, memory peak, filesystem and storage configuration.
8. **Load validity:** open-loop arrivals, fixed workload mix, bounded concurrency, warm-up, at least ten randomized repetitions, preserved raw requests/results and per-run environment manifest.
9. **Statistics:** report p50/p95/p99 and uncertainty; keep failed trials and distinguish correctness failures from harness/infrastructure failures.

## Architecture implications

- Do not select a language or runtime from the existing toy workload.
- Do not select SQLite/PostgreSQL/embedded KV from unnormalized durability modes.
- Keep runtime, storage adapter, and transport as separate experimental factors.
- First implement one semantically correct product workload on the existing reference host; then port the same contract to each candidate.
- Use the cgroup v2 CPU controller for controlled accounting. Keep the /proc sampler as diagnostic telemetry only; its 5 ms polling can miss short-lived descendants and process reparenting.

## Next measurable milestone

A candidate is eligible for the product benchmark only after it passes:
- the same black-box control-plane contract;
- all mandatory storage conformance tests;
- crash/recovery and idempotency race tests;
- a harness self-test that proves cgroup membership covers the full candidate process tree.

Until then, publish only build/conformance and sampler smoke results. No weighted score or architecture winner is permitted.
