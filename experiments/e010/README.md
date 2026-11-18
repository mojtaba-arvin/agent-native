# E-010 isolated sandbox apply demo

This experiment demonstrates a real-agent service lifecycle:

`inspect → propose → validate → plan → apply → runtime request → audit`.

The only apply path is an explicitly injected `SandboxApplyCoordinator` backed by a private temporary SQLite directory. It publishes an immutable `ServiceRuntime` snapshot with one allowlisted built-in handler, performs a real runtime request, and records append-only SQLite audit events.

The default E-009 Gateway continues to reject `service.apply`. No production service, deployment target, external database, or external credential is configured by this experiment. This experiment uses the complete snapshot proposal path; it does not establish delta-proposal apply semantics. E-007's snapshot/delta factorial remains no-apply.

Run locally after starting Ollama:

```bash
python experiments/e010/run_demo.py --model qwen3:8b
```

The run artifact includes the provider trace, per-turn prompt-state snapshots, run record, sandbox database, and audit database.
