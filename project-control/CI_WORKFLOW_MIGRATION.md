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

- **Layer 0:** fast, changed-path-aware, parallel deterministic checks on every PR; pushes are limited to `main` and `research/**`. There are no workflow/job concurrency groups: each run is allowed to finish so an update cannot intentionally cancel an in-flight extended-evidence job.
- **Layer 1:** native/database/container checks on relevant PRs and pushes, all merge groups, and nightly. A separate impact job uses GitHub's API; API errors fail safe by enabling Layer 1.
- **Layer 2:** model trials, the ten-repetition E-002 benchmark matrix, E-009 ten-repetition capacity confirmation, and lockfile generation are explicit manual dispatches. No expensive benchmark schedule remains.
- **Model evidence:** the current Qwen3/Ollama job runs on a standard CPU runner and is explicitly diagnostic, not M3 acceptance. Decision-grade M3 evidence still requires an approved GPU or API path.
- **Permissions:** read-only by default; issue comments receive `issues: write` only in the two evidence-publishing jobs.
- **Evidence:** benchmark/model/performance outputs remain downloadable artifacts; E-007 and E-009 issue references are preserved.

## Review boundary

The 15 workflow deletions exist only on this stacked branch. The unified workflow has been exercised on the PR head. PR #65 must remain stacked until PR #64 is integrated; then retarget it to research/reboot-core and require a fresh green run against the updated base before merging. No branch protection, merge queue, secrets, production deployment, or release settings are changed here.


## Verified PR-head execution

Run [44424340406](https://github.com/mojtaba-arvin/agent-native/actions/runs/44424340406) completed successfully on the unified-workflow PR head:

- Layer 0: 14/14 suites passed, 509 unit tests, four validator negative cases, 5.57 seconds
- Layer 1: native/container/database job passed; Go, Rust, WASI Preview 2, BEAM, PostgreSQL and cross-engine parity checks passed
- E-009 shared-runner product-path smoke passed with zero failed expectations in run 44424340406. A later run (44428316444) failed only the throughput/p99 capacity thresholds on the same shared runner; this exposed that the Layer 1 smoke was incorrectly enforcing a capacity gate despite its own non-capacity classification
- Manual E-002 ten-repetition matrix, E-009 ten-run confirmation, model diagnostics and lockfile generation were skipped as intended

The stale E-007 source-manifest reference has been corrected to hash .github/workflows/ci.yml. The workflow has no concurrency groups. This run verifies the PR head; after PR #64 merges, PR #65 still needs retargeting and a fresh run on research/reboot-core.

## Shared-runner threshold correction

Run [44428316444](https://github.com/mojtaba-arvin/agent-native/actions/runs/44428316444) passed the E-001/E-002 native and PostgreSQL checks but failed the E-009 smoke's 100 RPS and p99 <= 100 ms capacity thresholds. The request outcomes themselves had zero failed expectations; the artifact classifies this as a shared-runner product-path smoke, not a capacity claim. This is expected environmental variance, not a product correctness regression.

The normal Layer 1 job therefore runs the E-009 smoke without --enforce-capacity-gate. It continues to enforce the product-path expectations and uploads raw diagnostics. The controlled ten-repetition E-009 confirmation remains a separate manual job and retains the capacity gate. This separates deterministic correctness CI from environment-sensitive capacity evidence without deleting or weakening the actual capacity experiment.

**Post-correction verification:** Run [44428892897](https://github.com/mojtaba-arvin/agent-native/actions/runs/44428892897) passed Layer 0 and Layer 1 after the always-on E-009 smoke stopped enforcing the shared-runner capacity thresholds. The E-009 step had zero failed expectations and retained the explicit non-capacity classification. The separate manual ten-repetition job still has the capacity gate.
