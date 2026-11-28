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

Baseline measurements are observed. Exact-head post-change runs and cache-hit evidence are pending at the time this note is authored. No percentage or runner-minute savings are claimed until completed job timestamps and repeat-run cache outcomes are available.
