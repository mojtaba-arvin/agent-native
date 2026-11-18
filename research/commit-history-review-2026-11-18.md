# Commit-history review — Agent Native

**Snapshot reviewed:** 2026-11-18 (UTC)  
**Repository:** `mojtaba-arvin/agent-native`  
**Active integration branch at review start:** `research/reboot-core`  
**Purpose:** derive durable engineering/process rules from the commit graph, PR history, branch topology, CI runs, and real-agent artifacts. This is an engineering retrospective, not a claim that every historical code diff was re-audited line by line.

## 1. Scope and method

The review used GitHub's branch, commit, compare, pull-request, workflow-run, and artifact records.

- Enumerated all 19 remote branches visible before this review branch was created. All 19 reported `protected=false`.
- Retrieved the complete commit-message history of `research/reboot-core`: 798 commits from the initial repository commit (2026-11-16 09:02 UTC) through merge commit `ab7cc682` (2026-11-18 07:43 UTC).
- Compared every branch head against `research/reboot-core` to identify merge bases, ancestors, diverged branches, and unique-ahead counts. For divergent branches, inspected the unique commit-message ranges rather than summing shared history as if it were independent.
- Enumerated all 20 pull requests that existed at the snapshot and checked their base/head refs, merge state, changed-file counts, and commit counts.
- Correlated the history with E-007/E-010 workflow runs and inspected the First Light, Second Light, and E-010 artifacts/logs relevant to recent runner changes.

**Coverage boundary:** the 798-commit active-branch history was enumerated by commit metadata/message. Deep source-diff inspection concentrated on the architecture resets, E-007/E-009 runner/gateway changes, E-010 apply path, PRs #30–#34, and the corresponding artifacts. The review does not claim a line-by-line audit of every file in every historical commit.

## 2. What the history says

### 2.1 Commit activity is heavily evidence/documentation oriented

The 798 commits on `research/reboot-core` have the following subject-prefix distribution:

| Prefix | Commits | Share |
|---|---:|---:|
| `docs` | 264 | 33.1% |
| `test` | 124 | 15.5% |
| `pilot` | 106 | 13.3% |
| `fix` | 69 | 8.6% |
| `feat` | 34 | 4.3% |
| `ci` | 24 | 3.0% |
| `chore` | 21 | 2.6% |
| Other prefixes | 156 | 19.5% |

The combination of documentation, tests, and pilot commits is 61.9% of the active branch history. That reflects a valuable evidence-driven research process, but the sequence also shows many small adjacent commits whose only effect is to update test counts, workflow URLs, pending/completed labels, report summaries, or an evidence-index row.

**Learning:** evidence is a product artifact, but repeatedly committing near-identical status/count corrections fragments the causal history. Future work should keep the implementation/test change focused, then consolidate the corresponding evidence update into one coherent commit after CI and artifact adjudication.

### 2.2 The product reset is real, but the default branch does not expose it

The early history has a material direction change:

- PR #1 established the initial research foundation.
- PR #5 added an early FastAPI-oriented vertical slice.
- Both PRs were closed without being merged.
- PR #6 reset the project to an independent agent-first backend framework, not a wrapper around FastAPI/Django/etc.

At the reviewed snapshot, `main` still contained only the initial commit. PR #6 was open and Draft, targeting `main`, with 192 changed files and approximately 29.8k additions; its head was `research/reboot-core`.

**Learning:** the repository's default checkout and the active research/product source are different. A new contributor cloning `main` does not see the actual framework work. This is a significant publication/governance gap, not a reason to merge a very large Draft PR without a release review. The reset needs a deliberate integration/release plan: stable architecture boundaries, an evidence index, a clean baseline, and a reviewable merge decomposition or explicit milestone.

### 2.3 Branches are retained long after their PRs merge

At the branch snapshot there were 19 refs, none protected. The current integration branch had 797 commits ahead of `main` (798 including the root commit). The large ahead counts on other refs are mostly shared ancestry, not independent code.

Comparing branch heads to `research/reboot-core` showed:

| Branch | Relation to active base | Unique ahead / behind |
|---|---|---:|
| `research/reboot-core` | Same | 0 / 0 |
| `research/e007-post-proposal-failure-analysis` | Diverged | 115 / 49 |
| `docs/paper-evidence-skeleton` | Diverged | 113 / 49 |
| `feature/e007-compaction-opt-in` | Diverged | 107 / 49 |
| `fix/e007-absolute-request-deadline` | Diverged | 107 / 49 |
| `fix/agent-inspection-progression` | Diverged | 8 / 13 |
| `fix/e010-apply-contract-binding` | Diverged | 5 / 14 |
| `chore/refresh-real-agent-pins-after-squash` | Diverged | 4 / 12 |
| `fix/provider-absolute-deadline` | Diverged | 2 / 48 |
| `chore/e007-second-light-preflight` | Diverged | 1 / 48 |
| `decision/e002-agent-control-plane` | Diverged | 1 / 48 |
| `fix/e007-hard-deadline-reboot-core` | Diverged | 1 / 44 |
| `integration/e009-prevalidation` | Diverged | 1 / 49 |
| `feat/e010-isolated-sandbox-apply` | Ancestor | 0 / 24 |
| `feat/e010-real-agent-runner` | Ancestor | 0 / 20 |
| `fix/bounded-inspection-repeat` | Ancestor | 0 / 1 |
| `fix/e007-operation-catalog-guard-second-light` | Ancestor | 0 / 39 |
| `fix/e009-prompt-state-and-operation-guard` | Ancestor | 0 / 31 |
| `main` | Ancestor | 0 / 797 |

The large diverged E-007, paper, compaction, and deadline branches share much of their ancestry; these counts must not be added as independent commits.

The PR list contained 20 entries at the snapshot: 15 merged, 2 closed without merge (#1 and #5), and 3 open (#6, #17, #20). Many refs for merged PR branches still remain on GitHub.

**Learning:** branch count is not just cosmetic. Stale refs make it harder to determine the canonical source, and diverged refs increase the chance of selecting the wrong pin or accidentally reviving an obsolete implementation. Do not delete evidence-bearing branches blindly, but prune merged feature refs after verifying their commits are reachable from the intended integration line and no active PR/workflow still depends on them.

### 2.4 Squash merge and pinned revisions repeatedly conflicted

The history contains a concrete revision-provenance failure:

- PR #31's feature head was `cdaec444...`.
- It was squash-merged as `b85fda8...`.
- The post-merge runner pin was initially set to the feature-branch commit rather than the resulting base-branch commit.
- PR #32 then corrected the script and both dispatch manifests to pin the reachable squash-merge SHA.
- PR #33 was deliberately merged with a merge commit to preserve its source revision as an ancestor for the E-010 pinned runner.

**Learning:** a feature head SHA is not automatically a valid clean-checkout pin after squash merge. Every pin must be checked against the exact checkout/ref strategy. If a run must use a specific source commit, either preserve it in branch ancestry with a merge commit or pin to the actual merge commit and verify file hashes. Never rely on a commit that only existed on a deleted/rewritten PR head.

### 2.5 Workflow triggers are coupled to dispatch-manifest commits

E-007 and E-010 workflows listen to pushes on `research/**` when their respective dispatch manifest changes. This is useful for reproducibility, but it means that a “small” PR or post-merge correction to a dispatch file is also a real model run.

The history contains runs that were cancelled or superseded while pins/manifests were being corrected (for example, E-007/E-010 runs around SHAs `b85fda8` and `0d6dd43`). E-007 concurrency uses `cancel-in-progress: true`, so another run on the same ref can cancel an active one.

**Learning:** dispatch-manifest edits are experiments, not ordinary documentation. Do not bundle them casually with implementation PRs. Keep active runs immutable; make one deliberate dispatch change only after the exact source SHA, preflight, and CI are verified. A cancelled run is not an agent result and must not enter the lifecycle denominator.

## 3. Repeated technical failure patterns and corrections

### 3.1 Failure taxonomy must be grounded in raw evidence

The E-007 history repeatedly refined distinctions among:
- semantic agent errors (unknown operation, malformed proposal, invalid IR),
- Gateway contract errors,
- runner/process errors,
- provider transport/HTTP failures,
- timeout-at-wall-deadline symptoms,
- token/tool/wall-budget exhaustion,
- incomplete or ineligible measurement.

That refinement was necessary: a provider transport symptom at the exact wall ceiling is correlated with timeout, not proof of an independent outage; resource budget exhaustion is not an agent semantic failure; and a Gateway-accepted proposal is not a successful validate/plan lifecycle.

**Learning:** raw artifact + exact request/response trace + runner/provider logs are the minimum adjudication unit. A summary label alone is not a sufficient root cause.

### 3.2 The evaluator discarded the most useful startup evidence

Second Light workflow [44260660138](https://github.com/mojtaba-arvin/agent-native/actions/runs/44260660138) failed in approximately 35 microseconds with zero model tokens and zero tool calls. The evaluator returned `runner_result_missing`. Inspection of `eval_runner.py` showed that `subprocess.run(capture_output=True)` captured stderr, but the evaluator discarded it and retained only stdout. The actual child-process startup error therefore could not be recovered from the artifact.

**Correction:** PR [#34](https://github.com/mojtaba-arvin/agent-native/pull/34) now persists bounded stdout/stderr, exact argv and cwd, Python version, return code, elapsed time, output hashes, and truncation metadata; nonzero child exits with no run record are classified as `runner_process_failed`. Regression CI [44264343340](https://github.com/mojtaba-arvin/agent-native/actions/runs/44264343340) passed, and PR #34 merged as `7b389723...`.

**Learning:** every subprocess boundary must preserve stderr and exit metadata. “No result JSON” is a symptom, not a root cause.

### 3.3 Operation-selection and inspection loops must be stopped at the protocol boundary

Three real-agent observations show distinct protocol failures:

- First Light: model selected a new operation name as if it already existed. The catalog guard prevented the invalid call from reaching Gateway and pointed to `service.propose`.
- Second Light: the model eventually proposed, but sent malformed proposal envelopes and exceeded the original coarse repair key.
- E-010 run [44261051426](https://github.com/mojtaba-arvin/agent-native/actions/runs/44261051426), artifact [14408283754](https://github.com/mojtaba-arvin/agent-native/actions/runs/44261051426/artifacts/14408283754): the model first omitted `service_id`, then repeated service-level inspection. The Gateway provided exact operation names and a one-repair no-progress stop. The run terminated after 4 tool calls, 11,001 input tokens, 192 output tokens, and 139.769 seconds, with `inspection_progression_failed`. No individual operation was inspected; no propose, validate, plan, or apply occurred. Sandbox audit remained empty.

**Learning:** a useful protocol must make the next valid action explicit and preserve progress, but the runner must also terminate repeated no-progress behavior early. A clearer diagnostic is not proof that the model can follow it; real-agent evidence remains necessary.

### 3.4 Sandbox apply requires stronger binding than operation allowlisting

Review found that the first E-010 coordinator enforced the requested operation name/order but did not compare the whole proposed service/type/existing-operation snapshot exactly. The verifier also did not tie the apply result's returned change-set ID to the proposal hash.

**Correction:** PR #30 enforces exact baseline contract preservation and hash binding, with tests. E-010 remains strictly temporary-sandbox-only; the real model has not yet reached apply.

**Learning:** the authority boundary must revalidate the complete contract and identity at the point of mutation. Tests that construct a successful lifecycle directly are implementation verification, not evidence of a successful real-agent run.

## 4. Good patterns worth keeping

1. **Pre-registration and evidence gates.** The project distinguishes a proposal from validation/plan success, preserves negative findings, and avoids promoting deterministic provider-double tests into real-model claims.
2. **Immutable raw traces and provenance.** Per-turn prompt-state snapshots, payload hashes, exact operation inspection, and artifact-level source SHA make failures reproducible.
3. **Gateway-derived deterministic compaction.** The ledger is constructed from trusted Gateway state rather than an LLM-generated summary; raw traces remain append-only.
4. **Fail-closed runtime boundaries.** Default E-009 apply remains disabled; E-010 enables only an explicitly injected temporary sandbox coordinator.
5. **Deadline regression tests.** The slow-drip tests correctly distinguish a hard wall-clock deadline from a socket inactivity timeout.
6. **Bounded repair and resource rules.** The one-repair / stop-on-repeat behavior makes failure faster and less ambiguous without increasing Qwen budgets.

## 5. Operational rules adopted from this review

These rules should govern subsequent work on `research/reboot-core`:

| Rule | Required behavior |
|---|---|
| Source-of-truth | Always record base branch, merge base, source SHA, and whether the pinned commit is reachable from the exact checkout. |
| Pin discipline | After squash merges, repin to the resulting integration SHA. If a runner requires the feature commit itself, preserve it with merge ancestry and prove reachability. |
| Experiment immutability | Do not edit a dispatch manifest while its run is active. A dispatch-manifest change is an explicit experiment launch, not incidental documentation. |
| CI vs model execution | Separate deterministic CI changes from manifest/dispatch changes. Do not combine them in one PR unless a real-agent run is intentionally part of the change. |
| Cancellation | Treat cancelled workflows as infrastructure/experiment-control events, never as agent failures or valid repetitions. |
| Process diagnostics | Every subprocess captures, persists, and hashes stdout/stderr, exit code, argv, cwd, and elapsed time with restrictive file permissions. |
| Failure adjudication | Never infer timeout, prefill failure, model failure, or Gateway failure from an aggregate status without checking trace and provider/runtime logs. |
| Repair budget | Repair distinct diagnostics only within an explicit bounded budget; repeated same-state requests must stop at the runner/Gateway boundary. |
| Evidence cadence | Consolidate code, tests, and same-day evidence updates; avoid many commits that only churn test counts and “in progress” labels. |
| Branch hygiene | Keep active research/evidence branches; identify stale merged refs. Delete only after reachability and active-PR/workflow checks. |
| Product integrity | Continue treating Agent Native as its own programming model/runtime, not a framework wrapper. Keep E-007 no-apply and E-010 apply sandbox-only. |
| Main integration | PR #6 remains the Draft integration path to `main`; do not imply `main` contains the framework or merge it without a deliberate release review. |

## 6. Execution mistakes made during this work and safeguards

This review also records mistakes in the assistant-led execution process, rather than treating every repository defect as someone else's historical issue.

| Mistake | Observable consequence | Corrective rule now applied |
|---|---|---|
| I pinned a runner to the PR #31 feature-head SHA after squash merge instead of the resulting integration SHA. | The workflow checkout was not guaranteed to contain the pinned commit; PR #32 was required to realign pins. | Verify commit reachability from the exact post-merge checkout. After squash, pin the new integration SHA; preserve a feature SHA only with an explicit merge commit. |
| I updated dispatch manifests in closely spaced integration changes. | Push-triggered E-007/E-010 runs were cancelled or superseded (including runs 44260499142, 44260499159, and 44260660103) before producing valid repeat evidence. | Treat every manifest edit as an experiment launch. Wait for the current run to finish, then make one manifest change and verify exactly one resulting run. Do not bundle manifest changes with normal implementation/documentation commits. |
| I relied on a stale conversational PR-status summary for PR #23. | I described it as open although GitHub showed it had already merged into the E-007 research branch. | Re-read live PR state, merge SHA, base/head, and changed files before every status report or merge decision. Memory/history summaries are navigation aids, not authoritative state. |
| I accepted `runner_result_missing` as a sufficiently useful evaluator diagnosis without checking whether child-process stderr was retained. | Second Light 44260660138 failed before a model request, but its actual subprocess startup error was lost. | PR #34 now writes bounded stdout/stderr, argv, cwd, interpreter, exit code, timing, and hashes into a private artifact. A missing run record with nonzero exit is a distinct `runner_process_failed` class. |
| I updated progress/evidence notes before always rechecking whether the workflow had completed. | Some “in progress” statements became stale within the same work window. | Before publishing a status, query the current workflow run and artifact state; record exact timestamps and run IDs. |

These are process defects with observable consequences. The changes above reduce recurrence, but they do not prove a real-model lifecycle succeeds.

## 7. Current state after this review

- Active base: `research/reboot-core`; PR #34 merged as `7b3897232e87e2e610db498047288b360b39cf0e`.
- The commit-history review was added in PR #35 and merged as `f4c1be0839003b059912f315192101c959ff3ce0`.
- PR #36 intentionally aligned the Second Light pin to the diagnostics-enabled source, added stderr-diagnostics preflight, and refreshed only the E-007 dispatch manifest. It merged as `a2a293266770426e0db6edc5cb84318b7a6ad97c`.
- The new E-007 run [44265332133](https://github.com/mojtaba-arvin/agent-native/actions/runs/44265332133) is queued/running on the PR #36 merge push. Its task, model, seed, temperature, context, token/tool/wall budgets are unchanged.
- The prior E-007 workflow 44260660138 is not a model/lifecycle failure: it ended before a child run or model request and its stderr was not preserved by the old evaluator.
- E-010 workflow 44261051426 is a genuine model-protocol no-progress failure: four tool calls, 11,001 input tokens, 192 output tokens, 139.769 seconds; no operation inspection, propose, validate, plan, or apply.
- PR #6 remains open/Draft; PR #17 remains open/Draft; PR #20 remains open. None is merged by this review.
- No remote branch deletions, default-branch changes, Qwen budget increases, GPU changes, or PR #17 merges were performed.

## 8. Immediate next work

1. Analyze workflow 44265332133's child-process diagnostic artifact. If the original process-start failure is fixed, adjudicate its actual lifecycle trace; if it fails again, use captured stderr and the exact source manifest to make one focused correction.
2. Continue E-010 only from the current artifact and protocol findings. Its four-call termination validates bounded stopping, not lifecycle success or apply.
3. Keep Third Light gated on actual progress to a real validate opportunity; a workflow completion or an infrastructure/process failure is not such an opportunity.
