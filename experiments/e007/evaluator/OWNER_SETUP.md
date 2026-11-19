# M3 evaluator owner setup checklist

This checklist prepares the owner-controlled execution boundary. It does not
create secrets, configure GitHub settings, approve spending, or enable dispatch.

## 1. Protected GitHub Environment

- [ ] Create an environment named `m3-evaluator`.
- [ ] Require explicit owner approval before the evaluator job starts.
- [ ] Restrict deployment branches to the reviewed M3 evaluation branch.
- [ ] Keep the environment unavailable to the agent-generation job.
- [ ] Record the environment protection configuration as reviewable evidence.

## 2. Oracle custody

- [ ] Store the oracle decryption key only as an environment-scoped secret in
      `m3-evaluator`; never as a repository-wide secret or agent-job secret.
- [ ] Keep oracle fixtures in a private owner-controlled source, not in the
      repository, workflow artifacts, caches, or agent workspace.
- [ ] Provision the oracle into a fresh evaluator-only directory with directory
      mode `0700` and file mode `0600`.
- [ ] Verify the evaluator sees the oracle while the agent job cannot list,
      mount, decrypt, or read it.
- [ ] Ensure the evaluator job never uploads oracle contents, paths, keys, or
      derived answer text. Upload only score summaries and opaque evidence IDs.
- [ ] Rotate the key after the evaluation and remove temporary runner storage.

## 3. Runner and image

- [ ] Use an ephemeral isolated runner; do not reuse a persistent self-hosted
      runner shared with the agent job.
- [ ] Pin the evaluator container image by immutable digest, not a mutable tag.
- [ ] Pin the OS, Python/runtime versions, evaluator dependencies, and scoring
      code revision.
- [ ] Disable unnecessary network egress from the evaluator job.
- [ ] Confirm the agent job and evaluator job do not share writable volumes,
      caches, home directories, or process namespaces.
- [ ] Preserve the runner image digest and environment inventory in the run
      manifest.

## 4. Model and spend approval

- [ ] Select exact provider/model identifiers and immutable model versions for
      strong, medium, and weak tiers.
- [ ] Record provider API version, region, endpoint, sampling parameters,
      context limits, and tool configuration.
- [ ] Set per-run and cohort-wide USD ceilings before any provider call.
- [ ] Set token, tool-call, wall-time, retry, and concurrency budgets.
- [ ] Ensure the credential used by the agent job cannot access the oracle.
- [ ] Confirm billing alerts and hard spend enforcement; an alert alone is not a
      hard ceiling.
- [ ] Obtain explicit owner approval for the final budget and execution path.

## 5. Freeze the preregistration

- [ ] Pin the three public task files and their SHA-256 hashes.
- [ ] Pin the evaluator/scoring revision and schema version.
- [ ] Freeze the 2x2 proposal/disclosure design, randomization seed procedure,
      repetitions per cell, and sampling parameters.
- [ ] Define eligibility, timeout, retry, failure, and missing-data treatment.
- [ ] Preserve all raw traces, failed runs, timeouts, invalid trials, and
      ineligible runs; never convert unknown cost or missing results to zero.
- [ ] Hash the complete cohort manifest and add it to
      `project-control/PREREGISTRATIONS.json` only after every required field
      is fixed.

## 6. Preflight and independent verification

- [ ] Run the boundary tests and verify the candidate hash is identical across
      proposal, semantic validation, and plan.
- [ ] Verify `no_apply=true` and prove no apply endpoint or handler is invoked.
- [ ] Run a canary with a synthetic oracle and no paid provider calls.
- [ ] Have an independent reviewer inspect the workflow, environment boundary,
      artifact handling, and cost controls.
- [ ] Enable the paid cohort only after every checkbox above has evidence.

## Current status

The repository currently contains a boundary preflight scaffold only. Actual
process isolation, GitHub Environment setup, oracle provisioning, model
selection, spend approval, frozen preregistration, and paid execution are not
implemented. Keep `execution_allowed=false` until the owner gates above are
verified.
