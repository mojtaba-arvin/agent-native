# Research and experiment code boundary

Everything under this directory is a research artifact or controlled demonstration, not an installed Python package and not a stable import surface.

- E-001 through E-008 contain parser, semantics, security, interface, persistence, evaluation, and experiment prototypes.
- E-009 `serve.py`, `kernel.py`, and `agent_gateway.py` are legacy demo entry points. They retain repository-relative import bootstrapping for reproducible historical experiments. New package and CLI code must import from `src/agent_native`, never from these scripts.
- E-010 is an isolated sandbox-apply demonstration. It deliberately depends on the E-009 prototype and is not a production apply path, package API, or deployable runtime.
- Research scripts may use `sys.path` bootstrapping internally. Such bootstrapping is prohibited in the supported `src/agent_native` package and any installed CLI entry point.

The compatibility boundary is explicit: legacy experiment commands remain available for reproducibility while the supported package namespace is migrated and tested independently. A future migration may replace these scripts with thin compatibility wrappers, but must preserve the deterministic experiment suite before removing the old entry points.
