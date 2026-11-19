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

For PR #81, the owner authorized a narrow waiver for head
`8f6ea008ef80cf0a1ef0d29ac503f5214ad5497e`. The exact marker is recorded in
the PR conversation:

`OWNER-APPROVED-REVIEW-WAIVER: 8f6ea008ef80cf0a1ef0d29ac503f5214ad5497e`

CI accepts this exception only when the PR author is the repository owner and
a comment authored by that same repository owner contains the exact current
head marker. Any new commit invalidates the waiver automatically.

- [x] Record owner authorization on PR #81's exact current head.
- [ ] Confirm the owner-waiver gate and fresh Layer 0/Layer 1 checks pass.
- [ ] Complete a source-level security audit and preserve its findings.
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

- [ ] Complete the steps in [E-007 evaluator owner setup](../experiments/e007/evaluator/OWNER_SETUP.md).
- [ ] Configure protected environment, evaluator-only oracle custody, and an
      isolated ephemeral runner.
- [ ] Approve exact model identities, repetitions, and hard spend ceilings.
- [ ] Keep the cohort draft and non-executable until all evidence is frozen.

No additional ChatGPT/GitHub code permission is required for ordinary branch,
file, PR, and CI work. Administrative settings, reviewer invitations, and
secrets remain owner-controlled.
