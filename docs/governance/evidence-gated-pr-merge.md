# Evidence-gated PR review and integration

## Purpose

Permit the implementer to review and merge their own code without pretending that self-review is independent peer review. Merge is an integration decision based on reproducible evidence; it does not mark a research milestone, security property, model capability, or product feature accepted.

## Required evidence

Before merge, record against the exact PR head SHA:
1. Intended base branch and merge-base freshness.
2. Complete diff reviewed, including generated files, workflow permissions, dependencies, and security-sensitive paths.
3. Acceptance command and targeted tests.
4. Full relevant regression suite (Layer 0 and Layer 1 where applicable).
5. New negative/security regression tests for material auth, authorization, identity, capability, allowlist, audit, apply, or rollback changes.
6. Required GitHub status checks green on the exact head.
7. All material review threads resolved or explicitly documented with rationale.
8. Remaining limitations and external gates.

The implementer may author this review record. Specialist review is useful for high-risk changes when available, but a second human approval is not a universal merge gate.

## GitHub review semantics

GitHub does not permit the PR author to submit a formal approval of their own PR. Do not create a fake approval, claim an independent review, or simulate another identity. Record 'implementer self-review' with the exact SHA and findings instead.

## Merge

The implementer may merge once the evidence above is complete and GitHub reports the PR mergeable. Use the repository's permitted merge method and expected-head protection. Never bypass required checks, branch protection, rulesets, or merge queues. If a repository ruleset still demands an independent approval solely due to reviewer identity, that is an administrative configuration blocker, not a reason to fabricate an approval.

## Separate authorizations that remain

This policy does not authorize paid API/GPU workloads, production deployment, secrets or protected-environment changes, destructive actions, repository security-setting changes, or hidden-oracle access. These remain subject to their own explicit authorization and technical isolation requirements.

## Acceptance

Merge does not close an Issue or mark a milestone complete unless its independent acceptance criteria and evidence are satisfied. Negative results and limitations remain visible.
