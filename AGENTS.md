# Agent Operating Contract

This repository defines and builds a new backend framework. It is not an adapter, wrapper, generator, control plane, or management layer for FastAPI, Django, Go frameworks, or other existing backend frameworks.

## Mission

Create an independently executable backend framework whose programming model, language/syntax, compiler or interpreter, runtime, standard library, service model, and operational semantics are designed around AI agents as the primary builders and operators.

The framework must enable agents across capability levels to produce, verify, operate, and evolve production-grade distributed backend systems with measurably lower total cost and failure rates.

## Non-negotiable constraints

- Do not implement the framework as a layer on top of an existing backend framework.
- Do not select Python, Go, Rust, or any other implementation language by familiarity or popularity.
- Do not assume the framework must use a conventional general-purpose language. A purpose-built language, DSL, typed declarative model, or hybrid is in scope.
- Do not confuse a syntax that is easy to generate with a system that is safe, fast, operable, and maintainable.
- Do not claim performance, reliability, security, or agent-productivity improvements without reproducible measurements.
- Security properties must be enforced by the compiler/runtime and trusted components, never by prompt instructions alone.
- Existing languages, runtimes, frameworks, databases, protocols, and research are prior art and potential implementation components, not architectural parents.
- Human-readable docs are secondary. Canonical contracts, schemas, executable examples, test fixtures, benchmarks, and machine-readable decisions are primary.

## Autonomous execution

Agents should inspect the repository, form hypotheses, implement experiments, run tests, review diffs, record decisions, and continue without narrating progress to the user. Ask the user only for decisions that require personal authority, credentials, irreversible actions, or material spending.

v1 work follows docs/V1_PLAN.md on research/reboot-core. Task state lives in GitHub Issues. Do not edit project-control/.

## Required engineering loop

1. Read the current project contract and relevant decisions.
2. Identify the highest-risk unknown and formulate falsifiable hypotheses.
3. Design the smallest experiment that can distinguish competing options.
4. Implement executable prototypes, not prose-only proposals.
5. Measure correctness, agent effort, runtime behavior, and operational cost.
6. Reproduce results from a clean environment.
7. Record evidence, limitations, and decision status in the repository.
8. Continue until a meaningful gate is passed or a genuine blocker is reached.

## Evidence discipline

Every decision must be labeled as one of:
- `observed`: directly measured or verified.
- `supported`: backed by primary sources or repeatable external evidence.
- `hypothesis`: plausible but not yet tested.
- `decision`: chosen based on stated evidence and trade-offs.
- `rejected`: tested or reasoned against explicit criteria.

Do not turn hypotheses into facts. Preserve negative results. Benchmarks must include source, version, hardware, configuration, workload, repetitions, raw results, and scripts.

## Architecture boundary

The product is the framework itself. Its own core must own its service model, execution semantics, request lifecycle, concurrency model, inter-service communication semantics, data access contract, failure behavior, capability/security model, and developer/agent interface. It may reuse lower-level infrastructure when justified, but must not delegate its identity or core semantics to another backend framework.

## Agent-first interface requirements

- Deterministic, compact, typed contracts.
- Small number of composable concepts.
- Explicit effects and resource boundaries.
- Stable machine-readable diagnostics with locations and remediation identifiers.
- Local, fast, deterministic validation before expensive model/tool loops.
- Introspection that exposes actual runtime truth.
- Safe defaults and deny-by-default authority.
- Reproducible builds and deterministic behavior where practical.
- Compatibility/versioning rules that agents can apply mechanically.
- No hidden code execution during inspection or validation.

## Completion criteria

A feature is not complete because code compiles. It must have executable tests, negative tests, failure semantics, resource limits where relevant, compatibility implications, and evidence that an agent can use it reliably.

## GitHub Issue title convention

Every Issue title must use `<type>(<scope>): <short, clear description>`. Use one lowercase Conventional Commit type: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, or `revert`. Scope must be concise lowercase kebab-case and identify the affected domain/component. Keep priority, milestone, feature/command IDs, phase, agent identity, dates, and run metadata in labels, milestones, or the Issue body—not the title. Do not use bracketed prefixes, standalone priority codes, `Recover:`, or agent/supervisor identity prefixes. Use `chore(roadmap): ...` for milestone bookkeeping and `chore(supervisor): ...` for run ledgers. Preserve all Issue metadata and relationships when renaming; change only the title. See the [shared canonical contract](https://github.com/mojtaba-arvin/commands/blob/main/_shared/issue-title-contract.md).
