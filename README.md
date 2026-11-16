# Agent Native

Agent-first backend tooling. The initial executable slice provides a deterministic project contract, a FastAPI service scaffold, and machine-readable validation and verification.

## Install the framework

```bash
python -m pip install -e .
```

## Create and run a service

```bash
agent-native init orders-service --path ./orders-service
cd orders-service
python -m pip install -r requirements.txt
agent-native validate
agent-native verify
agent-native inspect
uvicorn main:app --reload
```

All commands emit JSON to stdout. A non-zero exit code indicates failure. The generated service exposes `GET /health` and `GET /items`.

## Agent execution contract

An agent operating on a project should use this sequence:

1. Run `agent-native inspect` and read the complete JSON result.
2. Read `agent-native.json` before changing service behavior.
3. Modify the application and its declared operations together.
4. Run `agent-native validate`.
5. Run `agent-native verify`.
6. Run the service's tests and any task-specific acceptance checks. `verify` is not a substitute for behavioral tests.
7. Return command outputs, exit codes, changed files, and unresolved risks as evidence.

Do not infer undeclared operations or silently widen the service contract.

## Service contract: `agent-native.json`

```json
{
  "schema_version": "1",
  "name": "orders-service",
  "version": "0.1.0",
  "entrypoint": "main:app",
  "operations": [
    {
      "id": "orders.list",
      "method": "GET",
      "path": "/orders",
      "summary": "List orders"
    }
  ]
}
```

The manifest is strict: unknown or missing keys, duplicate operation IDs, duplicate method/path pairs, invalid versions, and unsupported methods fail validation. Version 1 currently supports static paths only.

## Commands

| Command | Contract | Side effects |
|---|---|---|
| `agent-native init NAME --path DIR` | Scaffold a service; refuses non-empty targets | Creates files |
| `agent-native inspect` | Emit service contract and framework operations | Read-only |
| `agent-native validate` | Validate manifest structure and invariants | Read-only |
| `agent-native verify` | Compile Python sources, import the ASGI entrypoint, compare declared routes | Imports and executes project module code |

`verify` imports the configured entrypoint. Only run it against code the agent is authorized to execute. It does not start a server, call external services, run migrations, or prove endpoint behavior.

## Current implementation boundary

This is an early, executable vertical slice—not a production-ready framework. It currently provides:
- Python 3.11+ CLI and strict JSON service manifest.
- FastAPI/ASGI scaffold.
- Deterministic manifest, syntax, entrypoint, and declared-route checks.
- Machine-readable success/failure payloads and process exit codes.

Not implemented yet: database models/migrations, authentication/authorization, capability tokens, background jobs, distributed execution, deployment, rollback, runtime policy enforcement, and full behavioral/security verification. Do not use this release as a security boundary or expose generated services to untrusted traffic without adding those controls.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

The architecture and research documents remain hypotheses and design inputs; executable behavior is defined by the package and its tests.
