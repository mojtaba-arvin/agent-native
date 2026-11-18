# Fast-CI port audit

**Status:** review complete; implementation/port not yet approved by evidence.  
**Compared refs:** `research/reboot-core` vs `ci/m2-fast-pipeline`.  
**Baseline:** `research/reboot-core@23f9c77d8ce9a8d55895c6c4903a4ff409ba5781`.

## Repository relationship

GitHub compare reports the candidate branch as **diverged: 187 commits ahead and 37 behind**. Its diff is not a safe merge unit: besides CI, it contains E-002 adapter/trace work, E-007 dispatch/evaluation changes, E-009 kernel/security/performance changes, E-011 changes, and research/report edits. Do not merge or cherry-pick the branch wholesale.

The CI-specific candidate consists primarily of:
- `.github/workflows/ci.yml` (319 lines; replaces 15 existing workflow files in the candidate diff),
- `scripts/ci.py` (path-aware suite selection and parallel execution),
- `scripts/fast.sh` (small wrapper),
- the 0.01-second polling test adjustment in `experiments/e001/prototype/test_http_server.py`.

## What is promising

- Layer 0 runs deterministic Python suites in parallel and uses changed paths to avoid unrelated work.
- Per-command timeout is bounded; suite failures are preserved and the overall process exits non-zero.
- `merge_group` and nightly extended checks are separated from ordinary PR/push validation.
- Model evaluation and the benchmark matrix are explicit workflow-dispatch inputs rather than ordinary PR checks.
- The reboot-core base already contains the PostgreSQL adapter/conformance files, Rust lockfiles, and E-009 performance-smoke flags referenced by the candidate workflow. Those are not missing prerequisites on the verified base revision.
- Nine workflow runs associated with the reboot-core baseline revision were observed and all completed successfully.

## Required corrections before port

1. **Deleted paths are currently invisible.** `scripts/ci.py` calls `git diff --name-only --diff-filter=ACMRT`; the `D` status is excluded. Deleting source or test files can therefore skip the affected suite. Include deletions and add a regression test.
2. **Project control is not mapped.** Add a dedicated fast suite for `project_control.py validate` and `self-test`, selected by `project-control/**` and `project_control.py`.
3. **Push/PR duplication.** The candidate uses an unrestricted `push:` trigger and a separate `pull_request` trigger. Feature-branch commits can run L0 twice. Restrict push to `main` and `research/**` (PR covers feature branches) and normalize concurrency grouping with `github.ref_name` so push and PR events for the same branch share a group.
4. **Nightly benchmark cost.** The candidate's benchmark job runs on `schedule` as well as manual dispatch. The 10×5,000-request E-002 matrix must remain explicitly manual until a capacity/cost basis authorizes scheduled runs. Keep the extended conformance job nightly; remove schedule from the expensive matrix.
5. **Model execution substrate.** The candidate's model job installs Ollama and runs Qwen3 8B on `ubuntu-latest`. That is acceptable only as an explicitly labeled CPU diagnostic, not as the M3 capability gate. Do not claim model acceptance from this job. The M3 decision-grade cohort must use an approved GPU or API execution path.
6. **Suite-selection tests are absent.** Add unit tests for changed-path selection, cross-suite dependencies, workflow/script changes, project-control changes, and deleted files.
7. **Preserve evidence semantics.** Keep model/benchmark workflows manual-only, preserve artifacts and failure records, and do not weaken the current E-007 no-apply gate or E-009 trust-boundary tests.

## Recommended port sequence

1. Port `scripts/ci.py` and `scripts/fast.sh` onto a fresh branch from the verified reboot-core SHA, first with deletion handling, project-control suite mapping, and selector tests.
2. Run the path selector against a fixture matrix (including deleted files) and execute all selected deterministic suites.
3. Port the unified workflow policy only after confirming all 15 existing workflow responsibilities are preserved. Keep model runs manual-only and explicitly diagnostic until GPU/API execution is approved; make E-002 matrix manual-only.
4. Remove legacy workflow files only in the same reviewable PR that proves their responsibilities are covered by the unified workflow. Never merge the divergent staging branch.

## Evidence boundary

This is a static review of the candidate files and a compare of branch refs. The staging branch's reported 12/12 fast suites in 4.96 seconds are not evidence that the candidate runs unchanged on reboot-core. No performance claim is transferred to reboot-core until the port is executed on the target base.

## Target-branch runner port checkpoint

The fast runner, wrapper, and selector regression tests have now been added to the project-control PR. The runner includes the 12 deterministic suites from the staging candidate plus dedicated project-control and CI-selector suites (14 total), includes deleted paths in its diff filter, and disables rename collapsing so both sides of a move can select their suites.

The first two target-branch workflow attempts (runs 962 and 963) failed **before any suite executed**. The job log showed that checkout used the default shallow depth of one commit, so the PR base SHA was unavailable to `git diff`. This is a CI checkout/configuration failure, not a test failure. The workflow now sets `fetch-depth: 0`; the corrected run is still pending and must be inspected before CP-006 is complete.

The corrected reboot-core-based PR run (workflow run 967) completed successfully: **14/14 suites passed in 16.22 seconds**, with 509 unit tests plus four validator negative cases. The path selector and project-control suite were executed, not merely inspected. The E-009 suite was the longest at 15.29 seconds (131 tests); optimization opportunities should be measured separately rather than weakening coverage.

## Measured HTTP shutdown-poll optimization

Applied `poll_interval=0.01` to the four E-009 HTTP-server test threads and the E-001 prototype HTTP-server test thread. The same 14-suite CI cohort was rerun:

| Measurement | Before | After |
|---|---:|---:|
| Total fast CI wall time | 16.22 s | 5.79 s |
| E-009 suite wall time | 15.29 s | 5.34 s |
| E-001 suite wall time | 5.04 s | 0.41 s |

All 14 suites passed both times; coverage remained 509 unit tests plus four validator negative cases. Total wall time fell by 64.3% on these two GitHub-hosted runs. Treat this as a measured run-to-run comparison, not a cross-runner performance guarantee.
