# GitHub resource policy for Agent Native

**Status:** supported by current GitHub documentation; reviewed 2026-11-17  
**Scope:** the public `mojtaba-arvin/agent-native` repository and its GitHub Actions research workflows.

This document records the practical resource envelope and the operating policy for using GitHub-hosted infrastructure as the project's default experiment environment. GitHub's limits and pricing can change; re-check the linked primary documentation before materially increasing resource use.

## Findings

### Compute

- Standard GitHub-hosted runners are free for public repositories. This is not the same as unlimited hardware.
- The standard `ubuntu-latest` runner currently provides 4 vCPUs, 16 GB RAM, and 14 GB SSD.
- A GitHub-hosted job has a hard maximum execution time of 6 hours. A workflow can contain multiple jobs, each subject to its own limit.
- The documented standard-runner concurrency limit for GitHub Free is 20 simultaneous jobs. Repository/account-level scheduling and GitHub capacity can still delay starts.
- Larger runners are not free for public repositories. Do not select them without an explicit cost/benefit decision.

### Storage

- GitHub Free's included Actions artifact storage is 500 MB. Actions artifacts and GitHub Packages share the applicable allowance.
- Artifact and log retention defaults to 90 days; public repositories can configure 1–90 days. Each artifact can also set a shorter retention period.
- Actions cache storage defaults to 10 GB per repository and entries not accessed for more than 7 days are removed. Increasing the cache limit beyond the included amount can incur charges.
- Runner-local disk is ephemeral and is not a durable evidence store.

### API and automation

- Unauthenticated REST API requests for public data are limited to 60 requests/hour per originating IP.
- Authenticated user REST API requests generally have a 5,000 requests/hour primary limit; search endpoints and secondary limits are separate.
- Secondary limits include concurrency and content-generation throttles. Automation must use response headers, backoff, and bounded retries rather than tight polling.
- A GitHub Actions workflow must not poll Actions APIs continuously when a workflow completion event or a manual inspection is sufficient.

## Operating policy

1. **Prefer standard public runners.** Use `ubuntu-latest` for ordinary Linux tests and bounded CPU/RAM experiments. Do not use larger runners, paid compute, or self-hosted runners by default.
2. **Keep expensive model trials opt-in.** Real-model experiments use an explicit dispatch mechanism, explicit budgets, and a concurrency group. They must not run on ordinary pushes or pull requests. If a workflow exists only on a non-default research branch, `workflow_dispatch` cannot be relied on from the GitHub UI; use a narrowly path-filtered dispatch marker commit instead, and keep that marker out of unrelated push triggers.
3. **Bound every experiment.** Set job timeouts below GitHub's six-hour hard limit, plus independent model token, tool-call, context, and wall-clock budgets. Fail closed when a budget is exceeded.
4. **Treat the runner as disposable.** Write only compact, reproducible evidence to artifacts. Never upload model weights, dependency trees, temporary databases, or full runner images.
5. **Keep artifacts small and short-lived.** Use the shortest retention that still supports review. For a one-off real-model trial, 14 days is the current setting; extend only when a concrete review need exists.
6. **Cache only high-value dependencies.** Do not cache Ollama model weights by default: a multi-gigabyte cache consumes a substantial fraction of the 10 GB allowance and can cost more time to restore than a fresh pull. Reconsider only after measuring repeated pull time and cache restore time.
7. **Do not use Actions artifacts as the canonical research archive.** Commit small summaries, schemas, decisions, and reproducibility instructions. Keep bulky raw evidence only when needed, with explicit retention and provenance; publish durable datasets elsewhere only after choosing a suitable storage and licensing model.
8. **Minimize API traffic.** Batch reads, prefer event-driven workflows, avoid polling, respect rate-limit headers, and use bounded exponential backoff. Do not create one commit per generated result; aggregate related repository changes.
9. **Use least privilege.** Workflows declare only the permissions they need. Model-evaluation workflows must not receive deployment credentials or write permissions. Untrusted pull-request code must never receive secrets.
10. **Preserve evidence boundaries.** A green CI test proves the test protocol passed, not that a real model succeeded. A locally verified candidate is not independently accepted. Record runner/model/version/configuration and retain raw traces needed to reproduce the conclusion.

## Current repository application

- The repository is public and uses standard GitHub-hosted Linux runners; no larger runner or self-hosted runner is configured in the E-009 real-model trial.
- The standalone E-009 real-model workflow remains a one-job, 45-minute, serialized workflow with `contents: read` permissions. Its research-branch marker is `experiments/e009/dispatch.json`.
- The new E-007 real-agent evaluation workflow is opt-in through `workflow_dispatch` or a narrowly path-filtered `experiments/e007/dispatch.json` push marker. It runs three serial Qwen3 repetitions on one standard `ubuntu-latest` runner, has a 60-minute job timeout, uses `contents: read`, and uploads evidence for 14 days. It does not run on ordinary PRs and does not cache or upload model weights.
- The E-002 cross-runtime benchmark matrix is explicitly opt-in on manual dispatch (or a deliberately tagged `[benchmark]` push), now has a 60-minute job timeout, and runs ten randomized repetitions per candidate at 5,000 requests per run, concurrency 32, and warm-up 250. Artifacts are retained for 14 days, including partial artifacts after a matrix failure. Routine conformance jobs do not launch the matrix.
- Each E-007 real-agent repetition is bounded to 48,000 cumulative input tokens, 6,000 cumulative output tokens, 20 tool calls, 900 seconds of agent wall time, and an 8,192-token per-request model context. The job pulls Qwen3 once and reuses the local process across its three sequential repetitions; it does not cache model weights between jobs.
- The fifth standalone E-009 trial, [run 44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833), completed all six existing-operation inspections and reached proposal validation, but failed with `AN021` because the model supplied an object rather than the required input declaration array and repeated the same proposal. It used 33,714 input tokens, 1,314 output tokens, 12 tool calls, and about 12.75 minutes; no candidate or plan was produced.
- The first three-repetition E-007 Qwen3 evaluation, [run 44087224894](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087224894), is currently in progress. The ten-repetition E-002 diagnostic matrix, [run 44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181), is also in progress. Neither has an accepted result at this snapshot.
- Deterministic conformance workflows remain separate from real-model trials: a green result proves the reference tests passed, not that a model-driven change was completed. The real-agent eval gate is evaluated independently from those checks.

## Decision

For the current research phase, standard public GitHub-hosted runners are the correct default. The project's present workload does not justify paid larger runners, self-hosted infrastructure, or caching multi-gigabyte model weights. The limiting resource is not public-runner compute minutes; it is the finite runner hardware, per-job time ceiling, artifact/cache storage, concurrency, and the need to preserve high-quality evidence. Optimize those dimensions before adding infrastructure.

## Primary sources

- [GitHub Actions billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub-hosted runner selection and specifications](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
- [GitHub Actions limits](https://docs.github.com/en/actions/reference/limits)
- [GitHub Actions artifact and log retention settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)
- [Dependency cache limits and eviction](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
- [REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- [Workflow concurrency](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency)
