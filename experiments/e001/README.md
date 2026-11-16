# E-001 executable syntax prototype

Status: disposable research instrument; **not** the selected language, compiler architecture, or runtime.

This prototype tests one narrow question: can a small textual service declaration be parsed into a deterministic, typed-shape intermediate representation with useful source diagnostics?

It deliberately implements no HTTP server, database, network stack, framework adapter, or production runtime. Python is used only as a throwaway parser harness because this experiment concerns the representation, not the implementation language. That choice creates no implementation-language decision.

## Run

Requires Python 3.11+ and no third-party packages.

```sh
python -m unittest discover -s experiments/e001/prototype -v
python experiments/e001/prototype/agent_native.py experiments/e001/examples/catalog.an
```

The CLI emits canonical JSON to stdout and diagnostics to stderr. Exit status is non-zero for invalid input.

## Experimental limits

- Grammar covers service identity and operation contracts only.
- Types are opaque identifiers; no type checker or name resolution exists yet.
- Effects and capabilities are declared, not enforced.
- No claims about agent productivity, security, performance, or syntax superiority.
- Parser diagnostics have stable codes and line/column locations, but remediation quality remains to be tested.

## Next falsifiable tests

1. Compare this textual form against the same contract represented as structured JSON IR.
2. Have constrained, general, and advanced agents implement a hidden-test workload from a clean checkout.
3. Record tokens, tool calls, wall time, edits, parse/repair loops, and acceptance results.
4. Add a follow-up schema evolution task before considering any representation decision.


## Conventional-language contract baselines

- `baselines/go/`: standard-library Go domain service with explicit repository and authorization interfaces, deterministic error codes, validation, and in-memory storage.
- `baselines/rust/`: equivalent Rust domain service with traits, explicit authorization, deterministic errors, validation, and in-memory storage.

These are implementation baselines for measuring how agents express the same contract in conventional languages. They use no HTTP/backend framework and are not Agent Native's product implementation language. The DSL parser remains a contract front-end prototype; it does not yet execute the service or prove end-to-end task-cost advantages.
