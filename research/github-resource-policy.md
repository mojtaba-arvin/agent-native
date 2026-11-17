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
2. **Keep expensive model trials opt-in.** Real-model experiments use `workflow_dispatch`, explicit budgets, and a concurrency group. They must not run on every push or pull request.
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
- The E-009 real-model workflow is manual-only, has one job, uses a 45-minute job timeout, serializes runs, and has `contents: read` permissions.
- The E-002 cross-runtime benchmark matrix is now explicitly opt-in on manual dispatch (or a deliberately tagged `[benchmark]` push), has a 30-minute job timeout, and retains its artifact for 14 days. Routine manual dispatches still run conformance checks without launching the benchmark matrix.
- The trial is bounded to 24,000 input tokens, 6,000 output tokens, 20 tool calls, 900 seconds of agent wall time, and an 8,192-token model context.
- The workflow uploads the run record, tool trace, candidate, summary, console output, and model/runtime metadata for 14 days. It does not upload the model weights.
- The E-009 real-model workflow has been added but **has not yet been dispatched**. No real-model result is claimed.
- The latest inspected branch HEAD, `65234a604c015bf69d01acbd881097088ea69102`, has successful runs for the ten existing CI workflows (E-001–E-009 and the Agent Native pilot). This does not include a run of the manual-only real-model workflow.

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
