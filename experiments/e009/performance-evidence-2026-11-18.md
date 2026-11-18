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

## Next measurement gates

1. Repeat the same workload against PostgreSQL-backed admission with the same cgroup limits and identical request mix.
2. Run paired randomized SQLite/PostgreSQL cohorts (at least 10 per arm), report median and p95 across run-level p99/CPU, and retain raw artifacts.
3. Add 30-minute soak plus concurrent restart/crash/recovery cohorts before raising any capacity claim.
4. Only then use the shared adapter contract to compare runtime candidates; do not change workload, durability, or limits between candidates.

