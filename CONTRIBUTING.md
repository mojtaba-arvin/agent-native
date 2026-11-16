# Contributing to Agent Native

Agent Native is in its research and foundation phase. Contributions should strengthen the evidence base, clarify the problem, or validate a design hypothesis before expanding implementation scope.

## Before substantial work

- Read the README and relevant documents under docs/.
- Check open issues and current architecture decisions.
- For substantial research or implementation proposals, open an issue describing the problem, evidence, alternatives, and validation plan.
- Do not assume an unrecorded design choice has been accepted.

## Engineering standards

- Prefer small, reviewable changes.
- Keep generated artifacts reproducible and inspectable.
- Add tests for behavior and regression risks.
- Document security implications and side effects.
- Do not add mandatory dependencies without a clear justification.
- Do not claim performance, security, or agent-success improvements without reproducible evidence.

## Documentation and research

- Cite primary sources where possible.
- Record access date for time-sensitive material.
- Separate measured facts, published claims, hypotheses, and project results.
- Include limitations and counter-evidence.
- Do not copy benchmark datasets or source code without checking their licenses.

## Architecture decisions

Significant decisions must be recorded as ADRs under docs/adr/. Each ADR must include context, alternatives, evidence, consequences, and revisit triggers.

## Pull requests

A pull request should state:
- What problem it solves.
- Why the change belongs in this project.
- How it was tested or researched.
- Security, compatibility, and operational implications.
- Known limitations and follow-up work.

Avoid broad refactors unrelated to the stated problem.
