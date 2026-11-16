# E-005 agent-facing interface experiment

The framework's primary author/operator is an AI agent. This experiment tests a small, typed, progressive-disclosure tool surface. It does not select MCP, JSON-RPC, a CLI, or any transport as the final protocol.

## Prototype surface

- `interface.describe`: list compact tool summaries or retrieve one tool's full schema.
- `service.inspect`: read one service or one operation.
- `service.propose`: create an immutable, content-addressed change set against a base revision.
- `service.validate`: validate a proposed IR against trusted effect allowlists and structural invariants.
- `service.plan`: produce a no-side-effect plan and identify human approval gates.
- `service.apply`: deliberately disabled; returns a stable diagnostic and never mutates the service.

There is no shell, arbitrary file, arbitrary network, secret-read, or production-deploy tool.

## Run

```sh
python -m unittest discover -s experiments/e005 -v
```

## Design constraints

- Small discovery surface; fetch detailed schemas only when needed.
- Deterministic request/response envelopes and stable diagnostic codes.
- Read, propose, validate, and plan are separate operations.
- Proposals are immutable and tied to a base revision.
- The agent cannot approve its own high-impact actions.
- No side effects occur during inspect, propose, validate, or plan.
- Transport and final tool protocol remain open pending agent trials.
