# Owner actions required to remove external gates

This checklist is intentionally owner-operated. The agent may prepare branches,
tests, and reviewable PRs, but must not alter repository security settings,
merge to `main`, provision secrets, or authorize paid model workloads.

## A. M2-003 independent review or owner-authorized exception

The default policy remains two independent human APPROVED reviews on the exact
PR head. The repository owner may explicitly waive that requirement for one
exact head when external reviewers are unavailable. A waiver is not a peer
review, does not complete C3's independent-review criterion, and must never be
reported as two approvals.

For PR #81, the owner authorized a narrow waiver for the final reviewed head
`0e53539ac8652a79bd831c4883ec9ff26ebf411c`. The exact marker is recorded in
the PR conversation:

`OWNER-APPROVED-REVIEW-WAIVER: 0e53539ac8652a79bd831c4883ec9ff26ebf411c`

CI accepts this exception only when the PR author is the repository owner and
a comment authored by that same repository owner contains the exact current
head marker. Any new commit invalidates the waiver automatically.

- [x] Record owner authorization on PR #81's exact current head.
- [x] Confirm the owner-waiver gate and fresh Layer 0/Layer 1 checks pass on the final PR #81 head.
- [x] Complete a source-level security audit and preserve its findings in the PR conversation.
- [ ] Keep C3 pending until genuine independent peer reviews are obtained.

## B. Branch protection and main integration

The repository currently exposes an active ruleset named
`Protect Main Branch` with deletion and non-fast-forward protections. The
available integration connection cannot read the classic branch-protection
endpoint, so required-review and required-status-check settings are not
verified.

- [ ] Review the current `main` branch protection/ruleset in GitHub Settings.
- [ ] Require pull requests and at least two approving reviews for trust-boundary
      changes.
- [ ] Require the successful `Layer 0 · deterministic fast checks` and
      `Layer 1 · native, container, and database validation` checks where
      applicable.
- [ ] Require the branch to be up to date before merge; do not enable bypass
      for the PR author or automation.
- [ ] Review draft PR #6 before authorizing any integration into `main`.
- [ ] Explicitly authorize a main-branch merge only after review and checks.

## C. M3 decision-grade evaluation

The owner has authorized a zero-paid-spend ceiling, limited to GitHub Actions
free usage for this public repository. Paid API/GPU workloads are not
authorized. The existing Qwen3 CPU workflow remains diagnostic only.

- [x] Record the zero-paid-spend ceiling; do not incur paid model/GPU charges.
- [ ] Configure a protected environment and evaluator-only hidden-oracle custody; the current GitHub integration cannot write these administrative settings.
- [x] Implement and verify separate ephemeral agent/evaluator jobs, no-network containers, and runtime sandbox attestations in run #44494715332.
- [ ] Pin model identities, repetitions, and immutable cohort manifests using
      a qualifying free-tier execution path.
- [x] Keep the cohort draft and non-executable; no candidate model qualified (0/6 full lifecycle completions).
- [ ] Revisit model cohort selection only after M3-005's corrected provider-native schema run and protected evaluator setup.

No additional ChatGPT/GitHub code permission is required for ordinary branch,
file, PR, and CI work. Administrative settings, reviewer invitations, and
secrets remain owner-controlled.


## M3-003 — zero-cost model feasibility

- [x] Run the existing E009 local agent harness against three provisional open-weight CPU model tiers and both schema-disclosure arms on the public-repository GitHub Actions runner (run #44529848174).
- [x] Pin the Ollama runtime image and immutable per-model manifest/config digests in `experiments/e007/model-lock.json`; verify them again in the locked run.
- [x] Preserve all six model outcomes, tool traces, token usage, wall-clock measurements, and failures in artifact #14533985747; no selective retries.
- [ ] Keep model execution no-network, no-apply, and free of hidden-oracle data.
- [ ] Do not dispatch the M3 hidden-oracle cohort until model selection and protected Environment custody are verified.


## 19 November 2026 — provider-native tool schema implementation

- [x] Replace the provider-facing generic tool wrapper with provider-native Gateway functions while retaining the trusted Gateway dispatch envelope (PR #102).
- [x] Verify progressive discovery and upfront schema exposure with deterministic tests; verify undiscovered tools fail closed and disabled `service.apply` is not exposed.
- [x] Pass exact PR-head Layer 0 (143 E-009 tests) and Layer 1 (native/container/database/PostgreSQL/cgroup-v2) CI: run #44538804299.
- [ ] Inspect the fresh locked six-cell CPU feasibility artifact from run #44539287065; do not claim model qualification unless the full lifecycle and local verifier pass.


## 19 November 2026 — M3-005 locked rerun

- [x] Complete the unchanged six-cell provider-native schema rerun on the pinned Granite 4.0 model lock (run #44539287065).
- [x] Preserve artifact #14538178152 and all six raw traces; record the negative result (0/6 full lifecycle completions).
- [x] Keep the 12,000-token budget, model lock, no-network inference, no-apply, and zero-paid-spend boundary unchanged.
- [ ] Implement M3-008 duplicate-discovery/inspection guard and compact-state deduplication before another model run.
