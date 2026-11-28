# Research note: Issue title convention

**Classification:** repository process convention  
**Scope:** GitHub Issue metadata and v1 research workflow

## Problem

The repository needs predictable, searchable Issue titles without turning titles into execution ledgers. The existing v1 plan used a bracketed `[Txx]` prefix, while the repository-wide contract requires Conventional Commit-style titles. Keeping both rules would make task creation ambiguous and encourage priority, phase, or run metadata to leak into titles.

## Decision

Use `<type>(<scope>): <short, clear description>` for all Issues. The accepted lowercase types and title examples are maintained in `docs/issue-title-convention.md`, the public repository-owned source of usable guidance. `AGENTS.md` points contributors to that guide.

Task identity and scheduling remain separate metadata: v1 task IDs are written as `Task: Txx` in the Issue body; priority, milestone, labels, dependencies, attempt budgets, and run metadata remain in their corresponding GitHub fields or Issue body. The task branch naming convention `task/Txx-short-name` and PR base `research/reboot-core` are unchanged.

## Compatibility and boundaries

- No framework architecture, runtime, experiment protocol, or product decision changes.
- Existing Issue records are not bulk-renamed by this documentation change.
- When a title is corrected later, preserve all other Issue metadata and relationships.
- The public guidance is self-contained and does not depend on a separate control-plane repository.
- This note records the governance rationale; the canonical instructions remain in `docs/issue-title-convention.md`.

## Verification

`tests/test_issue_title_convention.py` checks the canonical format, allowed lowercase types, metadata placement, and removal of the conflicting v1 title prefix. GitHub Actions must validate the exact pull-request head before merge.
