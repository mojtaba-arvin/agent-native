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

- [ ] Run and verify the topology smoke's separate ephemeral GitHub-hosted jobs/runners; do not reuse a persistent self-hosted runner shared with the agent job.
- [x] Pin the topology-smoke Python container image by immutable multi-platform digest.
- [ ] Configure and verify actual protected Environment approval rules and evaluator-only oracle custody.
- [ ] Pin the OS, Python/runtime versions, evaluator dependencies, and scoring
      code revision.
- [ ] Disable unnecessary network egress from the evaluator job.
- [ ] Confirm the agent job and evaluator job do not share writable volumes,
      caches, home directories, or process namespaces.
- [ ] Preserve the runner image digest and environment inventory in the run
      manifest.

## 4. Model and spend approval

- [x] Record the owner-approved zero-paid-spend ceiling: GitHub Actions free usage for this public repository only.
- [ ] Select exact open-weight model identifiers and immutable model versions for strong, medium, and weak tiers using a qualifying free route.
- [ ] Record inference runtime version, quantization, sampling parameters, context limits, and tool configuration.
- [ ] Set token, tool-call, wall-time, retry, and concurrency budgets for the selected free route.
- [ ] Ensure any future agent credential cannot access the oracle.
- [ ] If no free model path meets the preregistered quality threshold, do not run a decision-grade cohort; do not substitute a paid provider.

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
- [x] Implement a synthetic-oracle topology smoke with no paid provider calls.
- [ ] Run it after merge to research/reboot-core and preserve its score artifact.
- [ ] Verify protected environment configuration, oracle custody, and separate runner trust zones.
- [ ] Have an independent reviewer inspect the workflow, environment boundary, artifact handling, and zero-cost controls.
- [ ] Keep the real model cohort disabled until every required checkbox has evidence; paid execution is not authorized.

## Current status

The repository now contains boundary preflight checks and a synthetic topology-smoke workflow scaffold. The smoke uses separate ephemeral jobs, a no-network agent container, a synthetic evaluator-only oracle, and allowlisted artifacts; it has not yet been executed on the integrated research branch. Actual protected Environment rules, hidden-oracle provisioning, model selection, frozen preregistration, and real cohort execution remain unimplemented. The owner-approved spend ceiling is zero paid spend. Keep `execution_allowed=false` until the owner gates above are verified.
