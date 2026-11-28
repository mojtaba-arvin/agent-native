# GitHub Issue title convention

Use this format for every Issue in this repository:

```text
<type>(<scope>): <short, clear description>
```

The title is a compact statement of the change or question. It is not a task ledger or execution record.

## Types

Use one lowercase Conventional Commit type:

- `feat` — introduce user-visible or framework capability
- `fix` — correct incorrect behavior
- `docs` — documentation or contributor guidance
- `refactor` — restructure without changing externally observable behavior
- `test` — add or improve tests and validation fixtures
- `build` — packaging, dependencies, or build-system changes
- `ci` — continuous-integration workflows and automation
- `chore` — maintenance that does not fit another type
- `perf` — performance improvement
- `revert` — revert an earlier change

## Scope and description

- Use a concise, lowercase kebab-case scope naming the affected domain or component.
- Keep the description short, clear, and specific; use sentence case only where normal prose requires it.
- Do not add a trailing period.
- Do not use bracketed prefixes, standalone priority codes, or identity prefixes such as `Recover:`, agent names, or supervisor names.

Examples:

| Good | Why |
|---|---|
| `docs(governance): define issue title convention` | Documentation change with a clear scope |
| `feat(gateway): expose bounded proposal inspection` | Capability and affected component are explicit |
| `fix(runtime): reject expired capability grants` | Corrective change is easy to classify |
| `test(e007): preserve proposal lifecycle evidence` | Research identifier is a scope, not a title prefix |

## Keep tracking metadata out of titles

Put priority, milestone, task/feature/command IDs, phase, agent identity, dates, attempt counts, and run metadata in GitHub labels, milestone fields, or the Issue body. For v1 tasks, put the identifier in the body as `Task: Txx`; keep the `v1` and `kind:*` labels and dependency/acceptance fields intact.

Examples:

- Good title: `test(e007): preserve proposal lifecycle evidence`
- Body metadata: `Task: T43`, `Priority: P1`, `Run: 123456789`
- Avoid: `[T43] [P1] test(e007): preserve proposal lifecycle evidence`
- Avoid: `P1 T43 test(e007): preserve proposal lifecycle evidence`
- Avoid: `Recover: test(e007): preserve proposal lifecycle evidence`

When updating an existing Issue title, change only the title. Preserve its body, labels, milestone, assignees, dependencies, comments, and other relationships.

## Research branch conventions

This title convention does not change the repository's research workflow. v1 task branches and pull requests continue to use `research/reboot-core` as their base, following `docs/V1_PLAN.md`. Task IDs remain in Issue bodies and PR bodies (for example, `Task: T43`), not in Issue titles or branch-name prefixes.

The repository's architecture and evidence rules in `AGENTS.md`, `VISION.md`, `DESIGN_SPACE.md`, `EVALUATION.md`, and `DECISIONS.json` remain authoritative.
