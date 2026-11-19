# E-007 evaluator isolation preflight

This directory contains only the evaluator boundary contract and tests. It
contains no oracle fixtures, provider credentials, or hidden expected answers.

## Required execution topology

1. The agent job receives public task prompts and writes a candidate artifact.
2. The agent job has no oracle mount, decryption key, evaluator environment, or
   provider credential beyond the separately approved model-call credential.
3. A separate protected evaluator job downloads only the candidate artifact.
4. The evaluator job receives the oracle through an owner-provisioned,
   owner-only file outside the agent workspace. The oracle key is available only
   to the protected evaluator environment.
5. The evaluator checks proposal/validation/plan candidate-hash continuity,
   no_apply, and oracle path separation before scoring.
6. Only score summaries, raw-trace references, and evidence hashes leave the
   evaluator job. Oracle contents and paths are never uploaded as artifacts.

## What is implemented here

- `boundary.py` rejects oracle paths inside the workspace, symlinks, non-regular
  files, additional hard links, wrong file/directory ownership, group/world
  accessible oracle files or parent directories, and candidate artifacts
  outside the agent workspace.
- It validates that proposal, semantic validation, and safe plan use one
  candidate hash and that apply was not invoked.
- These checks are defense-in-depth preflight checks only. They do not provide
  process, filesystem, network, container, or VM isolation and do not claim
  that the evaluator is safe to run against an untrusted agent on the same host.

## Owner setup still required

See [OWNER_SETUP.md](OWNER_SETUP.md) for the complete security, runner, model-budget, preregistration, and preflight checklist.

- Configure a protected GitHub Environment named `m3-evaluator`.
- Provision the oracle decryption key only to that environment (never to the
  agent job).
- Select an isolated ephemeral runner/container image and pin its digest.
- Approve the model provider, model identities, repetitions, and spend ceilings
  before freezing the preregistration.

Until those controls are configured and independently verified,
`evaluator_isolation.implemented` remains false and the M3 cohort remains a
non-executable draft.
