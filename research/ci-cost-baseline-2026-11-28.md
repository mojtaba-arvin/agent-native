# CI cost optimization: measured baseline and safeguards

Date: 2026-11-28

## Goal

Reduce avoidable CI wall time and runner consumption without weakening the evidence required for the agent-native runtime, storage, and distributed-execution experiments.

## Observed baseline

The following values come from GitHub Actions job and step timestamps, not estimates:

| Workflow/job | Observed duration | Relevant work |
|---|---:|---|
| Agent Native CI, Layer 0 | ~4s | Deterministic path-selected suites |
| Agent Native CI, Layer 1 | 3m20s | Go, Rust, WASI, BEAM, PostgreSQL, cgroup smoke |
| T16 immutable benchmark image | 3m31s | Python contract tests, Go/Rust tests, Docker image build |
| T16 Docker build step | 1m35s | Builds native candidates into immutable benchmark image |
| E-002 Rust runtime step | 44s | Locked Rust tests, release build, conformance |
| PostgreSQL adapter/parity step | 48s | PostgreSQL reference adapter and cross-engine trace parity |
| E-009 cgroup smoke | 24s | Containerized capacity smoke |

A recent PR revision ran Agent Native CI Layer 1 and T16 image concurrently, for approximately 6m56s combined wall time. This is not a runner-minute total; job duration and wall time are distinct measures.

## Changes implemented in PR #312

- T16 image and preflight workflows now declare path filters for their relevant workflow and source inputs. Their manual dispatch remains available, and the dedicated T16 task branch remains configured.
- Go module caches are keyed from checked-in go.mod manifests.
- Rust build caches cover the baseline/runtime/WASI workspaces and the T16 Rust candidate.
- T16 BuildKit uses the GitHub Actions cache backend for Docker layers.
- The CI extended-check classifier no longer treats every .github or scripts edit as a reason to run the entire native/database lane. It continues to route CI workflow, acceptance/gate, T16, recovery, preflight, runtime, test, database, and experiment changes to extended validation.

## Preserved correctness and evidence

No test suite or acceptance step was removed. The extended lane still runs E-001 Go/Rust baselines, E-002 Go/Rust/WASI/BEAM runtime conformance, PostgreSQL storage and cross-engine parity, and E-009 cgroup smoke. T16 retains its contract tests, native candidate tests, digest-pinned base-image resolution, exact source SHA/build-time binding, Docker smoke checks, and publication guard. Scheduled/default-branch and explicit manual performance/model workflows remain separate from deterministic PR feedback.

Crash recovery, lease fencing, retry/deadline/cancellation behavior, atomic effects, persistence, schema evolution, and multi-process semantics remain covered by their existing test suites. No model call or credential was added to deterministic CI. Model feasibility/cohort evidence is not inferred from fixtures.

## Validation status

Exact-head deterministic, native/database, T16 image, T16 preflight, E-007 preflight, task-gate, task-acceptance, and commit-identity checks passed on head 573454a064031037eaa674dfd62a16eef0b4dd44. The zero-job M3-007 push failure remains a separate pre-existing anomaly and is not a required check.

## Final policy and measured exact-head result (2026-11-28)

The repeat BuildKit run confirmed cache reuse. Go and Rust builder layers were reported as cached, the T16 image workflow imports the shared cache without exporting it, and the preflight cache marker was restored on a same-source update. The marker-hit path was observed: the cache marker restore completed, the conditional cache-export step was skipped, and the BuildKit export was not repeated.

Exact-head run on `573454a064031037eaa674dfd62a16eef0b4dd44`:

| Job | Baseline | Final policy | Delta |
|---|---:|---:|---:|
| Agent Native CI Layer 1 | 200s | 145s | -55s |
| Agent Native CI Layer 0 | 6s | 28s | +22s (full deterministic suite selected because workflow/test files changed) |
| CI change detection | 5s | 4s | -1s |
| T16 image | 211s | 150s | -61s |
| T16 preflight | 192s | 162s | -30s |

Combined measured runner time for these jobs fell from about 614s to 489s, a reduction of 125s (about 2.1 runner-minutes / 20.4%) on this T16-relevant PR. T16 image's Docker build step fell from 95s to 70s; T16 preflight's build step fell from 86s to 72s. Go and Rust caches were restored. The native lane's Go, Rust, and PostgreSQL parity steps fell from 16s, 44s, and 48s to 3s, 23s, and 33s. PostgreSQL parity and cgroup validation remained enabled and passed.

A docs-only PR has not yet been used to measure the T16 path-filter skip. The two T16 workflows previously consumed about 403 runner-seconds combined, so that is the baseline work expected to be avoided for unrelated docs changes; this remains an expected, not measured, saving.
