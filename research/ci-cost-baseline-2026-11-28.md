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

Baseline measurements are observed. Exact-head post-change runs have passed, but the first Buildx cache population added 30–32 seconds to the two T16 workflows. The 74.5s cache export is a warm-up cost. A repeat run is required to verify cache hits and net savings; no BuildKit savings are claimed until then.


## Exact-head cold-cache measurement (2026-11-28)

Measured on PR #312 head 19e1d5913f43aecc62f07f8a9d0958950ee7f7b3:

| Job | Baseline | Cold Buildx/cache run | Delta |
|---|---:|---:|---:|
| Agent Native CI Layer 1 | 200s | 164s | -36s |
| Agent Native CI Layer 0 | 6s | 23s | +17s (this PR changed workflow/test configuration, selecting all deterministic suites) |
| T16 image | 211s | 241s | +30s |
| T16 preflight | 192s | 224s | +32s |

The T16 Buildx runs successfully imported a GHA cache manifest and exported the first full cache. The preflight cache export took 74.5s (62.3s sending cache layers); this is a cold-cache warm-up cost, not a saving. Go and Rust dependency/build caches were restored in the T16 and native CI jobs. The Dockerfile's Go/Rust builder layers were not reported as cache hits on this first Buildx run.

This cold run is not evidence of a net T16 saving. A repeat exact-source build is required to verify cache reuse and whether avoiding repeated layer uploads offsets the initial export cost. Do not claim BuildKit savings until that repeat run is measured. T16 preflight and image checks, native/database tests, and all required checks completed successfully on this head.
