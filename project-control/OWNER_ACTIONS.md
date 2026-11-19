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
- [ ] Keep the cohort draft and non-executable until all evidence is frozen.

No additional ChatGPT/GitHub code permission is required for ordinary branch,
file, PR, and CI work. Administrative settings, reviewer invitations, and
secrets remain owner-controlled.
