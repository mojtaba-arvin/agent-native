# T09 controlled-host measurement

**Task:** T09 (#113)  
**Candidates:** Go/net-http, Rust/Tokio+Hyper, WASI Preview 2/Wasmtime, Elixir/BEAM  
**Runtime selection:** none

## Registered protocol

- 10 repetitions per candidate, with candidate order randomized independently for each repetition (40 candidate runs total).
- 5,000 measured GET /work?ms=0 requests per repetition, concurrency 32, warm-up 250.
- The measured request succeeds only for HTTP 200 with the exact body completed:0.
- The independent request generator is a compiled Go net/http binary; Python only orchestrates Docker and aggregates result files.
- Candidate processes run one at a time in separate Docker containers with cgroup v2 limits of one CPU (cpu.max = 100000 100000), a single pinned host CPU, and 2 GiB memory.
- The Go load generator runs outside the candidate cgroup and is pinned to a different host CPU. Candidate CPU usage is measured from cpu.stat usage_usec deltas; throttling and memory.peak are preserved.
- Candidate order is randomized per repetition using seed 20261120. Each response is retained as a JSONL record; per-run summaries, host metadata, protocol, and the aggregate matrix are retained with the same artifact.

## Verification matrix

- Go load generator: go test, go vet, and a Linux build using the pinned Go 1.23.12 toolchain.
- Controlled-host protocol: Python unit tests for cgroup cpu.stat parsing, one-vCPU quota validation, CPU-set parsing, and descriptive distributions.
- Existing shared HTTP conformance: each candidate must already pass the E-002 readiness, work, malformed-query, deadline, and streaming checks.
- Controlled run: all 40 candidate repetitions must complete with zero unexpected responses; otherwise the matrix fails and partial raw evidence is still uploaded.
- CI artifact: e002-controlled-cgroup-matrix, with 90-day retention and per-request JSONL traces.

## Evidence boundary

This is a controlled one-vCPU cgroup-v2 container measurement on an ephemeral GitHub-hosted VM. The candidate cgroup and load-generator CPU are isolated from each other, and the candidate CPU quota/accounting is enforced and recorded. It is **not dedicated bare-metal evidence**: the workflow cannot establish exclusive physical-host tenancy or remove hypervisor/neighbor noise.

The workload remains the existing trivial in-memory HTTP endpoint. It does not exercise the authenticated control-plane lifecycle, durable audit, PostgreSQL, outbox/idempotency, or the product workload design. Results are a controlled-cgroup diagnostic for the current E-002 probes, not a product SLO or decision-grade runtime selection. **no runtime is selected.**
