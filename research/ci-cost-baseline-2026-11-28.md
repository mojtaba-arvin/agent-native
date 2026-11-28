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

Exact-head deterministic, native/database, T16 image, T16 preflight, E-007 preflight, task-gate, task-acceptance, and commit-identity checks passed on the final policy head. The zero-job M3-007 push failure remains a separate pre-existing anomaly and is not a required check.

## Final policy and measured exact-head result (2026-11-28)

The repeat run on head 438f3db963b2e1a1f1d36f5c834c43c5e10c7b5d verified BuildKit layer reuse (Go and Rust builder layers were reported as cached). The repeat T16 image job fell from 241s cold to 191s; preflight fell from 224s to 187s. Both workflows still exported the cache in that experiment, so the cache export cost remained.

The final implementation changes the cache policy:
- T16 image imports the shared BuildKit cache and does not export it.
- T16 preflight is the sole cache writer. It exports only when an actions/cache marker keyed to the T16 Dockerfile and E-002 source fingerprint is missing, then writes the marker. Same-source PR updates should restore the marker and skip repeated exports.
- Go and Rust caches remain enabled in both T16 workflows.

Exact-head run on e0887d3b0f22dab32d95b52c94a6b099c7781977:

| Job | Baseline | Final policy | Delta |
|---|---:|---:|---:|
| Agent Native CI Layer 1 | 200s | 158s | -42s |
| Agent Native CI Layer 0 | 6s | 28s | +22s (full deterministic suite selected because workflow/test files changed) |
| T16 image | 211s | 159s | -52s |
| T16 preflight | 192s | 242s | +50s (first cache-marker miss and cache population) |

Including change detection, the measured runner-time reduction for this relevant PR is approximately 22 seconds. The final preflight run was the cache-marker miss and saved the marker successfully; a subsequent same-source update is required to observe the marker-hit path and confirm that the cache export is skipped. No additional savings are claimed until that run.

A docs-only PR has not yet been used to measure the T16 path-filter skip. The two T16 workflows previously consumed about 403 runner-seconds combined, so that is the maximum baseline work avoided for a docs-only change if both are skipped; this remains an expected, not measured, saving.
