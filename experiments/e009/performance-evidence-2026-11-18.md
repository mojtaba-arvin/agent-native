# E-009 resource-limited product-path performance evidence — 2026-11-18

## Result

**The first repeatable resource-limited E-009 product-path cohort passed its preregistered 100 req/s target.** This is a single-runtime confirmation, not a cross-runtime capacity ranking or production capacity certification.

- Workflow: [E-009 integrated framework-kernel checks, run 44345238807](https://github.com/mojtaba-arvin/agent-native/actions/runs/44345238807)
- Commit: `e6799d768bdd955d3aae6baeb0e89660230c4cdf`
- Server isolation: Docker container with cgroup v2 `cpu.max=100000 100000` (1 CPU) and `memory.max=1073741824` (1 GiB)
- Load shape: 10 repetitions × 1,000 requests; open-loop 100 offered req/s; concurrency 32; FULL SQLite audit durability enabled
- Outcome: 10,000/10,000 requests accounted for; 0 unexpected outcomes
- Response distribution: 8,000 HTTP 200, 1,000 HTTP 202 (durable job admission), 1,000 HTTP 401 (expected unauthenticated denial)

## Aggregate measurements

| Metric | Observed |
|---|---:|
| Achieved throughput | 100.044 req/s |
| End-to-end p50 | 5.094 ms |
| End-to-end p95 | 5.630 ms |
| End-to-end p99 | 6.536 ms |
| Service-only p99 | 6.430 ms |
| Client scheduling queue p99 | 0.128 ms |
| Server CPU during load | 21.651 CPU-seconds / 99.956 s |
| One-core utilization | 21.66% |
| Peak cgroup memory | 36,888,576 bytes (35.18 MiB) |
| Current cgroup tasks at sample | 3 |
| Durable audit events committed | 9,091 |
| Durable job submissions | 1,011 (including setup/control records) |

Across the ten individual repetitions, achieved throughput ranged from 100.042 to 100.046 req/s; p99 ranged from 6.314 to 7.420 ms. The full JSON artifact is attached to the workflow run as `e009-performance-smoke`.

## Interpretation against the product workload gate

The current preregistered control-plane target is 100 completed req/s, concurrency 32, p99 ≤100 ms and CPU ≤50% of one core, with expected denials counted as completed outcomes and durable audit enabled.

This cohort meets those four measured gates:
- throughput: 100.044 req/s ≥100;
- p99: 6.536 ms ≤100 ms;
- CPU: 21.66% ≤50%;
- unexpected outcomes: 0.

The measured p99 is approximately 15.3× below the 100 ms ceiling. The observed CPU is 28.34 percentage points below the 50% ceiling.

## What this does and does not establish

Established:
- The E-009 SQLite-backed control-plane path can sustain the target arrival rate in this specific one-CPU/1-GiB container configuration for ten consecutive 10-second cohorts.
- CPU usage and peak memory were read from the server container's cgroup v2, not inferred from the client or host process tree.
- The workload includes authorized reads, durable job admissions, and expected unauthenticated denials; FULL audit durability remained enabled.

Not established:
- This was run on a shared GitHub-hosted VM; the container limits the server, but host-level contention is not controlled.
- Only one E-009 process and one SQLite database were measured.
- No PostgreSQL-backed E-009 kernel, Go/Rust/WASI/BEAM runtime, multi-process, multi-node, sustained soak, crash-under-load, or production deployment was included.
- This does not rank runtimes or databases and must not be used as a production capacity guarantee.

## CI acceptance gate

The harness now has an opt-in fail-closed capacity gate. The confirmatory workflow enables it and fails unless throughput is at least 100 req/s, aggregate p99 is at most 100 ms, CPU is at most 50% of one core, peak cgroup memory is at most 1 GiB, the server cgroup is exactly one CPU / 1 GiB, and unexpected outcomes are zero. Unit tests cover pass, p99 regression, and missing/unlimited cgroup accounting.


The next cgroup cohort is a **0.5 ms audit-window comparison**, holding the 1-CPU/1-GiB limits, 100 req/s arrival rate, concurrency 32, request mix, FULL durability and all capacity thresholds constant. It also records cgroup CPU throttling, I/O counters and CPU/I/O/memory pressure at both load boundaries. This is a distinct treatment from the failed 2 ms cohort; do not pool them as repeated measurements of one configuration.

## Next measurement gates

1. Repeat the same workload against PostgreSQL-backed admission with the same cgroup limits and identical request mix.
2. Run paired randomized SQLite/PostgreSQL cohorts (at least 10 per arm), report median and p95 across run-level p99/CPU, and retain raw artifacts.
3. Add 30-minute soak plus concurrent restart/crash/recovery cohorts before raising any capacity claim.
4. Only then use the shared adapter contract to compare runtime candidates; do not change workload, durability, or limits between candidates.


## Repeatability failure discovered by the enforced gate

A second cgroup-limited 10×1,000-request confirmation was run with the same 1-CPU/1-GiB limits and the same 100 req/s request mix. The newly enforced gate correctly **failed** this run: [workflow 44355728291](https://github.com/mojtaba-arvin/agent-native/actions/runs/44355728291).

| Metric | First cgroup cohort (44345238807) | Second cgroup cohort (44355728291) |
|---|---:|---:|
| Throughput | 100.044 req/s | 100.002 req/s |
| Aggregate p99 | 6.536 ms | 252.021 ms |
| Aggregate p95 | 5.630 ms | 86.733 ms |
| CPU | 21.66% of one core | 17.32% of one core |
| Peak cgroup memory | 35.18 MiB | 43.73 MiB |
| Unexpected outcomes | 0 | 0 |
| Capacity gate | Pass (measured retrospectively) | **Fail: p99 only** |

In the second cohort, 9/10 repetitions had p99 above 100 ms (range 84.05–411.37 ms); only repetition 3 passed. Client queue p99 was 0.339 ms aggregate, while service-only p99 was 251.916 ms, so most of the tail was inside the server path rather than client scheduling. All four operation categories showed elevated service p99. Throughput, CPU, memory and expected status counts remained within their thresholds.

A separate uncontainerized 0.5 ms audit-window cohort [workflow 44340325781](https://github.com/mojtaba-arvin/agent-native/actions/runs/44340325781) achieved 100.041 req/s and aggregate p99 23.560 ms, but 2/10 repetition p99 values were still above 100 ms (211.64 and 184.27 ms). It is not a controlled cgroup comparison.

**Decision:** do not claim repeatable p99 compliance and do not select an audit batching delay. The first cgroup cohort is a successful sample, not a stable SLO. The second cohort reveals severe tail variance under the same nominal limits. The harness now records cgroup CPU throttling counters, per-device I/O counters, and CPU/I/O/memory pressure snapshots so the next run can distinguish quota throttling, storage stalls, and host contention. Cgroup limits do not control host disk latency or shared-runner contention.

