# Evaluation and Benchmark Strategy

## Purpose

The framework must demonstrate that it improves real backend delivery for agents. Evaluation must compare complete workflows, not isolated code-generation quality.

## Primary evaluation unit

A **verified task delivery**: an agent receives a bounded backend requirement in a controlled repository, makes the required change, and produces an application that passes acceptance, regression, security, and operational checks.

## Benchmark task categories

1. Bootstrap a service from a natural-language requirement.
2. Add or change an API endpoint and its contract.
3. Add a data model and safe migration.
4. Implement authorization and tenant isolation.
5. Add a background task with retry and idempotency behavior.
6. Diagnose and repair a seeded defect.
7. Integrate an external service with failure handling.
8. Add observability and operational health checks.
9. Upgrade a dependency or framework version.
10. Deploy, verify, and roll back a service.
11. Extend an existing service without regressing behavior.
12. Respond to an adversarial or ambiguous requirement safely.

## Agent capability tiers

Use multiple representative agents or models, grouped by observed task performance rather than marketing labels:

- **Constrained:** limited context, weaker planning, basic tool use.
- **General:** competent coding and tool use, moderate context.
- **Advanced:** strong planning, broad context, reliable multi-step execution.

Record exact model/version, agent harness, tool configuration, context limit, sampling parameters, and date. Do not assume capability tiers remain stable over time.

## Comparison groups

Where feasible, compare:
- Agent Native prototype.
- A conventional backend framework selected as a fair baseline.
- A second established framework from a different ecosystem.
- A minimal hand-built service baseline where useful.

Use the same task requirements, agent/model, environment, time budget, and evaluation criteria. Document unavoidable differences.

## Metrics

### Outcome and quality
- Task completion rate.
- Acceptance-test pass rate.
- Regression-test pass rate.
- Security-policy pass rate.
- Migration safety and rollback success.
- Deployment and health-check success.
- Human acceptance where automated oracles are insufficient.

### Agent efficiency
- Input and output tokens.
- Tool calls and failed tool calls.
- Number of repair iterations.
- Wall-clock time.
- Human interventions and approval requests.
- Context consumed by framework discovery and documentation.

### Economic efficiency
- Model/API cost.
- Compute and infrastructure cost.
- Human review and intervention time.
- Total cost per accepted task.
- Cost of failed attempts and recovery.

### Runtime and operations
- Startup and readiness time.
- Throughput and latency under defined workloads.
- CPU and memory consumption.
- Image/artifact size.
- Dependency count and vulnerability exposure.
- Observability completeness.
- Recovery time for seeded failures.

## Experimental controls

- Pin framework and dependency versions.
- Pin task specifications and test harness versions.
- Use isolated, reproducible environments.
- Run repeated trials for stochastic agents.
- Report median, spread, and failure distributions, not only best runs.
- Separate model variance from framework effects.
- Keep task-specific oracle tests hidden from the agent where appropriate.
- Preserve complete traces and artifacts with secrets removed.
- Record environment failures separately from agent failures.
- Do not tune only against the public benchmark tasks.

## Quality gates

A task is not successful merely because code was generated or a server started. The task must satisfy its acceptance criteria and applicable regression, security, and operational checks.

A result should be reported as **inconclusive** if the environment or evaluator failed in a way that prevents a fair judgment.

## Initial benchmark deliverables

1. A small set of 10–15 carefully specified backend tasks.
2. An executable harness with deterministic setup and teardown.
3. Baseline runs on at least two existing frameworks.
4. A cost and trace collector.
5. A failure taxonomy.
6. A published protocol that allows independent reproduction.

## External research inputs

- ABC-Bench: backend-specific, end-to-end agent evaluation across languages and frameworks.
- GitTaskBench: repository-grounded tasks, practical success criteria, and economic evaluation.
- SWE-PolyBench: repository-level, multi-language software engineering tasks.
- SWE-bench and Terminal-Bench: useful complementary signals, but not substitutes for backend-specific deployment and operational evaluation.

Benchmark versions and external papers must be reviewed before implementation; this document is a strategy, not a claim that the project already has a benchmark suite.
