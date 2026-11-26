# E-010 isolated sandbox apply demo

This experiment demonstrates a real-agent service lifecycle:

`inspect → propose → validate → plan → apply → runtime request → audit`.

The only apply path is an explicitly injected `SandboxApplyCoordinator` backed by a private temporary SQLite directory. It constructs a new `ServiceRuntime` instance with one allowlisted built-in handler, smoke-tests the candidate before publication, serializes apply transitions within one coordinator process, and makes repeated application of the same immutable revision idempotent. The process-local lock is not a cross-process lock. The current `ServiceRuntime` implementation does not enforce deep immutability of its IR or handler mappings.

The default E-009 Gateway continues to reject `service.apply`. No production service, deployment target, external database, or external credential is configured by this experiment. This experiment uses the complete snapshot proposal path; it does not establish delta-proposal apply semantics. E-007's snapshot/delta factorial remains no-apply. The Gateway trusts the host-injected callback: the `sandbox_only` surface label is descriptive metadata, not an enforcement boundary or proof that an arbitrary callback is isolated. The isolation claim applies only to this exact coordinator implementation and its private temporary directory.

Run locally after starting Ollama:

```bash
python experiments/e010/run_demo.py --model qwen3:8b
```

The run artifact includes the provider trace, per-turn prompt-state snapshots, run record, sandbox database, and audit database.
