# Unified workflow responsibility matrix

This migration is intentionally stacked on PR #64 (`feat/project-control-plane`). It does not merge the divergent `ci/m2-fast-pipeline` branch. It replaces the 15 legacy workflow files only in this working branch.

| Legacy workflow | Unified responsibility | Trigger/policy |
|---|---|---|
| `e001-prototype.yml` | Layer 0: `e001-prototype` | Every PR/push selection through changed paths |
| `e002-native.yml` | Layer 0: `e002-python`; Layer 1: Go/Rust/WASI/BEAM/PostgreSQL; benchmark job | Native checks on relevant PRs, merge groups, and nightly; ten-repetition matrix manual-only |
| `e003-semantics.yml` | Layer 0: `e003-semantics` | Changed-path selection |
| `e004-security.yml` | Layer 0: `e004-security` | Changed-path selection plus E-004 → E-009 dependency |
| `e005-agent-interface.yml` | Layer 0: `e005-interface` | Changed-path selection |
| `e006-durable.yml` | Layer 0: `e006-durable` | Changed-path selection |
| `e007-benchmark-corpus.yml` | Layer 0: `e007-corpus` | Changed-path selection; deterministic only |
| `e007-real-agent-eval.yml` | Layer 2: `models` job, E-007 option | Explicit manual dispatch; CPU diagnostic only; issue #61 evidence comment retained |
| `e008-outbox.yml` | Layer 0: `e008-outbox` | Changed-path selection |
| `e009-kernel.yml` | Layer 0: `e009-kernel`; Layer 1 cgroup capacity smoke; manual ten-run confirmation | Native E-009 PR changes trigger Layer 1; expensive confirmation is manual; issue #58 evidence comment retained |
| `e009-real-agent.yml` | Layer 2: `models` job, E-009 option | Explicit manual dispatch; CPU diagnostic only |
| `e010-real-agent-demo.yml` | Layer 2: `models` job, E-010 option | Explicit manual dispatch; isolated demo |
| `e011-semantics.yml` | Layer 0: `e011-semantics` | Changed-path selection |
| `agent-native-pilot.yml` | Layer 0: `pilot-protocol` | E-001/E-005 dependencies select pilot tests |
| `generate-lockfiles.yml` | Layer 2: `lockfiles` job | Explicit manual dispatch; artifact only |

## Unified policy

- **Layer 0:** fast, changed-path-aware, parallel deterministic checks on every PR; pushes are limited to `main` and `research/**`. PR and push concurrency groups normalize to the same branch name, and newer Layer 0 runs may cancel stale ones.
- **Layer 1:** native/database/container checks on relevant PRs and pushes, all merge groups, and nightly. A separate impact job uses GitHub's API; API errors fail safe by enabling Layer 1.
- **Layer 2:** model trials, the ten-repetition E-002 benchmark matrix, E-009 ten-repetition capacity confirmation, and lockfile generation are explicit manual dispatches. No expensive benchmark schedule remains.
- **Model evidence:** the current Qwen3/Ollama job runs on a standard CPU runner and is explicitly diagnostic, not M3 acceptance. Decision-grade M3 evidence still requires an approved GPU or API path.
- **Permissions:** read-only by default; issue comments receive `issues: write` only in the two evidence-publishing jobs.
- **Evidence:** benchmark/model/performance outputs remain downloadable artifacts; E-007 and E-009 issue references are preserved.

## Review boundary

The 15 workflow deletions exist only on this stacked branch. The PR must not be merged until PR #64 is integrated and the unified workflow has completed its first authoritative run on a base branch that contains it. No branch protection, merge queue, secrets, production deployment, or release settings are changed here.

## First unified-workflow execution finding

The first run of the new workflow (run 18) parsed and started successfully. The impact detector completed, Layer 0 selected all 14 suites, and 13 passed. E-007 failed in two cases because `experiments/e007/eval_runner.py` still included the removed legacy workflow path in its source manifest. The manifest now hashes `.github/workflows/ci.yml` instead. Layer 1 native checks were running independently at the time this finding was recorded; a corrected Layer 0 rerun is required before the migration is considered verified.

## Concurrency safety finding

The first unified-workflow run completed Layer 0 but its workflow run was cancelled when a second run for the same PR started; the Layer 1 job was cancelled with it. The fast job's `cancel-in-progress: true` policy can therefore discard in-flight extended evidence even though Layer 1 itself is configured not to cancel. Because Layer 0 now completes in roughly five seconds, the unified workflow changes this to `cancel-in-progress: false`: runs for the same branch serialize instead of cancelling a workflow that may be collecting Layer 1 evidence. This is an intentional safety trade-off; avoid claiming independent L0 cancellation while both layers share one workflow run.

**Concurrency evidence qualification:** Runs 20 and 21 were cancelled during explicit PR draft/ready state transitions. Although the fast job still had `cancel-in-progress: true` at the time, the cancellation cannot be attributed to that setting with certainty. The policy is kept at `false` as the safer evidence-preserving default; run 25 is the first run using that setting and its Layer 1 job is queued, not yet verified.
