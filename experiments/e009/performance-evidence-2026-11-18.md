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


## 0.5 ms cgroup comparison — capacity gate passed

The first 0.5 ms audit-window cohort under the same 1-CPU/1-GiB cgroup limits passed the executable gate: [workflow 44357166863](https://github.com/mojtaba-arvin/agent-native/actions/runs/44357166863).

| Metric | Observed |
|---|---:|
| Requests / repetitions | 10,000 / 10 |
| Achieved throughput | 100.018 req/s |
| Aggregate p50 / p95 / p99 | 4.484 / 15.875 / 27.465 ms |
| Service-only p99 | 27.342 ms |
| Client queue p99 | 0.217 ms |
| Repetition p99 range | 8.671–69.714 ms (10/10 ≤100 ms) |
| Server CPU | 22.46% of one core |
| Peak cgroup memory | 39,129,088 bytes (37.30 MiB) |
| Unexpected outcomes | 0 |
| Capacity gate | **PASS** |

Cgroup evidence during the measured interval:
- CPU quota: exactly one core; 999 periods; **0 throttled periods and 0 throttled microseconds**.
- CPU pressure (some): approximately 0.148 seconds over the ~100-second cohort; no full CPU pressure.
- I/O pressure (some/full): approximately 3.61 / 3.59 seconds over the cohort.
- Memory pressure (some/full): 0 / 0.
- cgroup I/O counters recorded about 497.9 MB written and 246.6 MB discarded during the interval; these are container/device counters, not logical SQLite payload bytes.

The contrast with the 2 ms cgroup cohort is material: 2 ms had p99 252.021 ms and failed, while 0.5 ms had p99 27.465 ms and passed. This supports testing the shorter audit collection window further, but **does not yet prove causality or justify changing the default**: host I/O pressure and shared-runner effects remain, and each profile needs another independent cgroup cohort. The 0.5 ms cohort also shows that CPU quota throttling was not responsible for its tail.


A second independent 0.5 ms cgroup cohort is now requested with the identical request mix, 1-CPU/1-GiB limits, FULL audit durability, 100 req/s target and executable capacity gate. Keep this as a separate raw run; do not pool or average it with the first cohort until both individual runs pass.


## Default-setting verification

The E-009 implementation now defaults to a 0.5 ms audit collection window in both SQLiteAuditSink and the HTTP server CLI. The next cgroup cohort omits the CLI override and exercises this default directly, retaining FULL SQLite synchronous durability and the fail-closed capacity gate.


## Third 0.5 ms cohort — default verified, p99 gate failed under I/O pressure

The third cohort [workflow 44359451102](https://github.com/mojtaba-arvin/agent-native/actions/runs/44359451102) omitted the audit-delay CLI override and therefore exercised the new 0.5 ms application defaults directly. It completed 10,000 requests at 100.043 req/s with zero unexpected outcomes, but **failed the p99 gate**:

- Aggregate p50/p95/p99: 5.263 / 36.862 / 144.727 ms
- Service-only p99: 144.621 ms; client queue p99: 0.192 ms
- 3/10 repetition p99 values exceeded 100 ms; range 16.780–313.948 ms
- CPU: 20.37% of one core; peak cgroup memory: 41.82 MiB
- CPU throttling: 0 periods / 0 microseconds; memory pressure: 0
- I/O pressure: 4.12 s "some", 4.08 s "full" over ~100 seconds
- All capacity checks except aggregate p99 passed

This confirms the default is 0.5 ms, but it does **not** establish repeatable p99 compliance. Across three 0.5 ms cgroup cohorts, two passed and one failed; the failed cohort coincided with materially higher I/O pressure, no CPU throttling, and negligible client queue delay. That is consistent with server-side storage/host-I/O stalls, but does not prove causality. The median aggregate p99 across the three cohorts is 27.465 ms; the tail gate still fails in one of three runs.

**Decision:** retain 0.5 ms only as a provisional E-009 reference default because its median tail is better than the small 2 ms sample. Keep the fail-closed p99 gate. Do not claim a stable SLO or production capacity until repeated runs on a controlled I/O environment pass. The next experiment should compare the same FULL-durability workload on a dedicated runner or storage volume with observable fsync latency; do not weaken durability or hide I/O stalls by moving the database to tmpfs.


## Next experiment: 1.0 ms audit window and WAL size

The next cgroup cohort compares a 1.0 ms audit collection window against the 0.5 ms provisional default. It retains 1 CPU / 1 GiB, FULL durability, the same 100 req/s mix and the same fail-closed capacity gate. The harness now records SQLite database, WAL and SHM file sizes both during load and after graceful shutdown, to determine whether large WAL/checkpoint behavior coincides with high cgroup I/O pressure.

