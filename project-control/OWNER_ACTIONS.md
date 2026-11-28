# Owner actions and external gates

This file tracks actions that genuinely require repository-owner authority, external resources, or evidence unavailable to ordinary repository CI. It is not a blanket prohibition on implementer review or PR merge.

## A. PR review and integration

The implementer may inspect and document their own complete diff, run the required security/threat review, resolve review threads, and merge the PR once the exact-head evidence gates pass. GitHub does not permit an author to submit a formal approval of their own PR; do not fabricate one or describe self-review as independent peer review.

For every PR, record:
- exact head SHA and intended base;
- required Layer 0 and Layer 1 results for that exact SHA;
- targeted and full relevant regression results;
- security regression coverage for trust-boundary changes;
- merge-base freshness and mergeability;
- unresolved threads, with each either resolved or explicitly recorded as an accepted limitation.

The former two-independent-human-approval rule and exact-head owner-waiver mechanism are retired as repository policy. A GitHub ruleset that still requires an approval is an external repository setting and must be changed by an authorized owner; never bypass it.

## B. Repository administration and main integration

The repository has an active ruleset named 'Protect Main Branch'. The available integration connection has not verified every required-review and required-status-check setting.

- [ ] Inspect the active ruleset and verify required status checks.
- [ ] Remove any mandatory independent-approval count that exists solely to enforce reviewer identity separation.
- [ ] Keep pull-request, required-check, deletion, and non-fast-forward protections enabled.
- [ ] Keep exact-head Layer 0 / Layer 1 requirements where applicable and require the branch to be up to date.
- [ ] Do not grant bypass to agents or disable branch protection.
- [ ] Keep administrative settings, secrets, and access-control changes owner-controlled.

The implementer may merge a clean, evidence-complete PR when GitHub permits it. The user/owner does not need to issue a second per-PR merge authorization.

## C. M3 decision-grade evaluation

The zero-paid-spend ceiling remains in force. Paid API/GPU workloads are not authorized. The existing Qwen3 CPU workflow remains diagnostic only.

- [x] Record the zero-paid-spend ceiling; do not incur paid model/GPU charges.
- [ ] Configure a protected environment and evaluator-only hidden-oracle custody; this requires GitHub administrative settings.
- [x] Implement and verify separate ephemeral agent/evaluator jobs, no-network containers, and runtime sandbox attestations in run #44494715332.
- [ ] Pin model identities, repetitions, and immutable cohort manifests using a qualifying free-tier execution path.
- [x] Keep the cohort draft and non-executable; no candidate model qualified (0/6 full lifecycle completions).
- [ ] Revisit model cohort selection only after M3-005's corrected provider-native schema run and protected evaluator setup.

## Historical evidence

PR #81 used an owner-authored exact-head review-waiver marker under the former policy. That marker is historical evidence only; it is no longer required or used as a substitute for review.

No additional code permission is required for ordinary branch, file, PR, CI, self-review, or evidence-gated merge work. Paid workloads, production deployment, secrets, and administrative settings remain separately controlled.
