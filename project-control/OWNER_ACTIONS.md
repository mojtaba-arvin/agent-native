# Owner actions required to remove external gates

This checklist is intentionally owner-operated. The agent may prepare branches,
tests, and reviewable PRs, but must not alter repository security settings,
merge to `main`, provision secrets, or authorize paid model workloads.

## A. M2-003 independent review

- [ ] Add two independent human reviewers to the repository (read access or
      higher is sufficient to review).
- [ ] Request both reviewers on [PR #81](https://github.com/mojtaba-arvin/agent-native/pull/81).
- [ ] Each reviewer inspects the Gateway/authz diff and the security regression
      tests, then submits an APPROVED review.
- [ ] Do not count the PR author or bot accounts.
- [ ] After approvals, confirm the review gate and current-base CI checks pass.

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
