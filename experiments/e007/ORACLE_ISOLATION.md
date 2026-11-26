# Acceptance-oracle isolation contract

This document defines a security boundary for future benchmark runners. It does not claim that the current repository provides a sandbox.

## Trust zones

1. **Public task corpus:** task statements, task IDs, difficulty, and required capability labels. Safe to expose to an agent.
2. **Agent workspace:** one task prompt plus its generated workspace manifest. It must not contain oracle IDs, hidden tests, expected outputs, scoring rules, evaluator credentials, or other tasks' prompts.
3. **Agent execution environment:** disposable and untrusted. It receives only the workspace and explicitly approved tool/model interfaces. It must not receive the evaluator filesystem, process environment, credentials, or network routes by default.
4. **Evaluator environment:** trusted, separate execution boundary. It receives the candidate artifact read-only, the oracle package, and a machine-readable run manifest. It emits integrity-protected results and preserves raw traces.

## Required execution order

- Resolve the task ID against the public corpus.
- Materialize exactly one task prompt using `prepare_workspace.py`.
- Snapshot/hash the agent-visible workspace before execution.
- Run the agent in a disposable sandbox with explicit CPU, memory, process, disk, and wall-clock limits. Network access is denied unless a controlled model/tool gateway is explicitly configured.
- Export only the declared candidate artifact and raw telemetry.
- Destroy the agent sandbox.
- Start a separate evaluator sandbox. Mount the candidate artifact read-only and mount the oracle package only here.
- Run hidden acceptance checks and emit results without copying oracle content or revealing hidden assertions to the agent.
- Preserve source revisions, image digests, model IDs, tool policy, limits, oracle version, raw traces, and evaluator output hashes.

## Non-negotiable controls

- Never mount the oracle directory into the agent container, even read-only.
- Never pass oracle paths, oracle IDs, test names, expected values, evaluator environment variables, or scoring logic to the agent.
- Never run untrusted candidate code in the evaluator process or in the same filesystem/process namespace as oracle code.
- Do not rely on prompt instructions, hidden filenames, or obscurity as a security boundary.
- Use separate OS/container/VM isolation with a documented threat model; a Python subprocess or separate directory alone is not a sandbox.
- Treat candidate artifacts and agent-produced metadata as untrusted input. Evaluator parsers must enforce size, type, path, and resource limits.
- Keep oracle failure details private; return only stable public failure classes to the agent after the run has ended.

## Current implementation status

`prepare_workspace.py` implements only public-workspace materialization and tests that it exposes one task without oracle metadata. It does not execute agents, isolate processes, mount hidden oracles, or provide a sandbox. Those capabilities remain open work.
