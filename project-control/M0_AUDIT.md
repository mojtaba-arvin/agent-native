# M0 source and evidence audit

**Audit date:** 2026-11-19  
**Audited stack head:** `9e56e9bd250cf992443fc4077808f5bc2e0a4d25` (PR #68 stack)  
**Underlying implementation baseline:** `research/reboot-core@23f9c77d8ce9a8d55895c6c4903a4ff409ba5781`  
**Boundary:** this is a source audit of the proposed PR stack. PRs #64, #65, and #68 are not yet integrated into `research/reboot-core`.

## Executive verdict

Agent Native is still an executable research/prototype repository, not a v0.1 runtime. E-009 is a meaningful single-node vertical slice, but the repository does not yet meet the v0.1 requirements for package installation, service discovery/loading, general read/write operation proposals, independent dev apply/rollback, or production-grade identity/audit.

The main product risk is no longer lack of a runnable example. It is the gap between one fixed Catalog service and a reusable runtime/Gateway contract. The main evidence risk is that real-agent acceptance and runtime-substrate selection remain unproven.

## Evidence matrix

| Area | Verified current state | Evidence and limits |
|---|---|---|
| E-001 — representation/parser | Disposable Python parser and canonical IR prototype; Catalog-oriented fixtures and semantic checks. | [E-001 README](../experiments/e001/README.md), source [agent_native.py](../experiments/e001/prototype/agent_native.py) at `93f92ff`. Not packaged or selected as the final service language/syntax. |
| E-002 — runtime substrates | Go, Rust, WASI Preview 2, and BEAM baselines pass functional conformance, but two ten-run shared-host cohorts failed the historical provisional CPU screen. No runtime is selected. | [E-002 README](../experiments/e002/README.md) at `5817386`; product-capacity workload and 25 CPU-s/5,000-request bound remain a hypothesis, not a controlled measurement. Package-size results are host-specific diagnostics. |
| E-003 — semantics | Executable reference model for input validation, cooperative cancellation, and capacity accounting. | [E-003 README](../experiments/e003/README.md) at `6f97cd1`. It is provisional; production cancellation transport, process kill escalation, distributed persistence/fairness, and multi-process fault behavior remain open. |
| E-004 — security | Default-deny capability policy with explicit grants and structured reason-coded decisions. | [E-004 README](../experiments/e004/README.md) at `f60daed`. Not production identity, cryptographic grant, revocation, sandbox, secret-management, or network-egress enforcement. |
| E-005 — Agent interface | Progressive-disclosure interface reference with inspect/propose/validate/plan semantics. | [E-005 README](../experiments/e005/README.md) at `308f117`. No transport/protocol selected; mutation/approval semantics are not production-ready. |
| E-006 — durable execution | Single-node SQLite reference for jobs, leases/fencing, cancellation acknowledgement, and recovery. | [E-006 README](../experiments/e006/README.md) at `d82c9d7`. No production queue/persistence substrate or distributed worker identity selected. |
| E-007 — agent evaluation | One real-agent task runner and a public ten-task corpus exist. The corrected Qwen3 cohort was 0/3 accepted; later probes include one Gateway-accepted proposal that timed out before validation/plan. The second Light retry was ineligible and also did not complete a task. | [E-007 README](../experiments/e007/README.md) at `0687b04`; runs 44087982547, 44105440141, 44144939813, 44149712970, and 44270509877. The 2×2 factorial is implemented and its manifest is ready for manual dispatch, but **no real-model factorial run has been dispatched**. |
| E-008 — external effects | Transactional outbox/inbox reference with at-least-once relay delivery, fencing, and consumer deduplication. | [E-008 README](../experiments/e008/README.md) at `e1f82cd`. Does not prove exactly-once external effects or a production broker/multi-node design. |
| E-009 — integrated kernel | One Catalog service composes IR, typed routing/input binding, default-deny authorization, tenant-scoped SQLite, durable jobs, worker/relay, outbox/inbox, durable SQLite authorization audit, HTTP, and Agent inspect/propose/validate/plan Gateway. | [E-009 README](../experiments/e009/README.md) at `aae1796`; workflow 44341003787 passed 124 E-009 tests. This is a single-node semantic integration proof, not a general framework or production deployment. |
| E-010 — apply | A real-agent lifecycle demo can apply through a private temporary-directory SQLite SandboxApplyCoordinator. | [E-010 README](../experiments/e010/README.md) at `0f67f57`; pinned demo revision `a972418e5795a863a1435bf69cc6592e782c6abd`. The default E-009 Gateway still rejects apply. The `sandbox_only` label is descriptive metadata, not an enforcement boundary; only the exact coordinator implementation is isolated. |
| E-011 — inter-service | Research plan only; no transport, broker, database, mesh, runtime, or deployment technology selected. | [E-011 plan](../research/e011-interservice-communication-plan.md) at `8f30171`. Exit requires two independent services, synchronous/asynchronous flows, and injected failure evidence. |

## Cross-cutting implementation facts

1. **No installable Python package is established.** Root `pyproject.toml` and `setup.py` are absent on the audited revision. The current E-009 entry point, kernel, and Gateway insert experiment directories into `sys.path`; see `serve.py` (`14eb9d6`, lines 22–23), `kernel.py` (`7052c40`, lines 26–28), and `agent_gateway.py` (`b13da05`, lines 26–28). This is a concrete M1 blocker.
2. **The Gateway is not multi-service yet.** `AgentNativeGateway` constructs its interface with only `{"catalog": service_ir}`; the delta tool schema hard-codes `service_id = catalog`. Delta proposals are limited to one append-only GET operation with `repository.read` / `items.read`. See `agent_gateway.py` (`b13da05`, lines 47–98 and 185–190). This is a concrete M2 blocker.
3. **Default apply is disabled.** The Gateway has no apply callback by default; E-010 injects a specific sandbox callback. Do not equate that demonstration with the v0.1 independent deployment controller or production authority boundary.
4. **Identity remains a fixture.** `serve.py` wires `MemoryIdentityProvider` and binds to loopback; E-009 explicitly documents no cryptographic workload identity, key rotation, distributed revocation, or production token validation.
5. **Publication is process-local.** E-009's RuntimeRegistry atomically publishes a frozen in-process revision/runtime snapshot. It does not implement multi-process rollout, crash recovery, cross-node consistency, or rollback orchestration.
6. **Audit is durable but not tamper-evident.** SQLite allow/deny decisions persist and fail closed; there is no remote replication, retention policy, external access control, or cryptographic tamper evidence.

## Research integrity and stale-document findings

- `REPORT.md` still declares a 17 November snapshot. Its next-evidence list refers to workflow 44189163401 as in progress even though later E-007 outcomes are documented in the same repository. Its latest implementation-verification paragraph still says 80 E-009 tests, while E-009 README records 124 tests in workflow 44341003787.
- E-007 README line 83 repeats workflow 44144939813 as currently running, although the completed input-budget-exhaustion result is already described in lines 65–69. This is contradictory.
- `experiments/e007/dispatch-request.json` names the superseded `e007-real-agent-eval.yml`. The active factorial runner reads `experiments/e007/dispatch.json`; `run_factorial_pilot.sh` does not consume the older request file. Treat the latter as a historical request artifact, not the current dispatch source.
- E-009 performance documentation distinguishes its manually enforced capacity gate from always-on CI product-path smoke. The unified CI now runs the always-on smoke without `--enforce-capacity-gate`; the explicit manual ten-repetition confirmation retains the gate. Shared-runner product smoke must never be described as capacity acceptance.
- The 0.5 ms E-009 audit group-commit window is provisional. The evidence includes a passing cgroup cohort and a later default-setting cohort that failed p99 under elevated I/O pressure; repeatability is not established, so this is not a stable SLO or a production SQLite recommendation.
- `DECISIONS.json` contains 14 decisions: D-0001, D-0002, and D-0006 are decided; D-0003 through D-0005 and D-0007 through D-0014 remain open. No service syntax, runtime, persistence, transport, or production identity architecture has been selected.

## v0.1 gap assessment

| Milestone | Current gap |
|---|---|
| M0 — research integrity | Source/evidence audit and document reconciliation still need completion; preserve immutable run/commit evidence and preregistration boundaries. |
| M1 — installable core | Add package metadata, stable imports, a single CLI, and install/run/check/inspect entry points without promoting the Python prototype into a final runtime decision. |
| M2 — service/Gateway generalization | Replace fixed Catalog assumptions with manifest/service loading and declarative read/write handlers; prove a second service without changing core code. |
| M3 — real-agent acceptance | The 2×2 factorial is prepared but undispatched; Qwen3 CPU evidence is not accepted. Decision-grade evaluation needs an approved GPU/API path, budget, strong model, randomized repeated cohorts, and same-hash validate/plan evidence. |
| M4 — safe apply/rollback | Separate agent-writer from deployment-controller authority; apply only to dev, explicit opt-in, hash-bound plan, conformance/health gates, atomic publication, and rollback. E-010 is not this controller. |
| M5 — production-boundary hardening | Replace fixture identity, close audit atomicity/tamper-evidence gaps, add failure injection/SLO evidence, and finish quickstart/security/limitations docs before v0.1 release. |

## Immediate next actions

1. Reconcile `REPORT.md` and E-007 README with the latest completed evidence; retain old raw artifacts unchanged.
2. Preserve `dispatch-request.json` as a historical record but clearly identify `dispatch.json` as the active manual factorial manifest and `.github/workflows/ci.yml` as the current workflow.
3. Turn the M1/M2 gaps into small, independently verifiable task contracts after this audit is reviewed.
4. Do not run paid API/GPU cohorts, select a runtime, enable apply, or merge the PR stack to main without the required owner authority.
