# RPI Research — Evidence Audit

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Audited HEAD:** `97255f48d1a6ff77c0bdb550212ca609eca128f0`  
**Scope:** evidence-only audit. No source code, runtime architecture, or technology selection is changed by this document.

## Executive finding

The largest gap is not the absence of test infrastructure. The repository already has substantial conformance tests, a ten-task public benchmark corpus, provider-neutral telemetry aggregation, a protected-evaluator contract, a paired-trial analyzer, and a real local-model runner for E-009. The gap is that these pieces have not yet been joined into a repeatable, independently scored agent-evaluation loop.

The fifth E-009 Qwen3 trial is new evidence not reflected in the older `REPORT.md` and resource-policy snapshot. It completed service inspection and all six existing-operation inspections, created a proposal, and reached validation. Validation rejected the proposed IR with `AN021`; the model then repeated the same proposal, and the runner terminated with `multiple_successful_proposals`. This is real-model execution evidence, but not a successful task, not a validated candidate, and not an E-007 benchmark result.

## 1. Evaluation-loop gap audit

| Required evaluation criterion | Current state | Existing evidence | Gap / sufficiency |
|---|---|---|---|
| Public task definitions | Implemented | E-007 contains 10 task statements spanning CRUD, schema evolution, tenancy, idempotency, deadlines, streaming, durable recovery, security, debugging, and safe planning | **Sufficient for a first public corpus**, not sufficient as a complete benchmark distribution |
| Agent execution runner | Partial | E-009 `local_agent.py` executes a real Ollama model against the live Agent Gateway; the separate pilot has an adapter and batch runner | **Insufficient for E-007**: there is no generic E-007 task runner that prepares a workspace, executes an agent, and exports a candidate |
| Real-model execution evidence | Partial, failed trials only | Five bounded Qwen3/Ollama attempts are recorded in the current work history; trial 5 is Actions run [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833) | **Insufficient for acceptance or productivity claims**: no successful end-to-end E-009 task yet |
| Independent acceptance oracle | Contract designed, implementation absent | `experiments/e007/ORACLE_ISOLATION.md`; pilot finalizer/evaluator-result contract; E-009 local candidate verifier | **Insufficient**: public E-007 has no private oracle package or separate evaluator execution boundary. E-009's verifier is trusted runner-side validation of one fixed proposal, not a hidden benchmark oracle |
| Scorers | Partial primitives, no eval cases | E-007 `metrics.py` aggregates accepted outcomes and operational metrics; E-009 verifier checks exact candidate/trace invariants | **Insufficient as a first-class eval system**: no declarative eval-case format, scorer registry, per-scorer threshold report, or E-007 runner |
| Trace and usage telemetry | Implemented as schemas/aggregators and pilot wiring | E-007 trace schema and strict aggregator; pilot provider-usage path and provenance checks; E-009 provider-reported token counts | **Sufficient foundations**, but real-run data is sparse and incomplete as a benchmark corpus |
| Failure classification | Implemented in parts | E-007 distinguishes invalid tool calls, schema errors, business tool errors, and ineligible infrastructure failures; pilot finalizer preserves failed/interrupted runs | **Sufficient foundations**, but the five E-009 model failures need a common durable result taxonomy and analysis |
| Repetition and statistical analysis | Partial | E-002 matrix supports seeded randomized repetitions; pilot analyzer reports paired differences, bootstrap intervals, and exact McNemar results | **Insufficient real-agent evidence**: no completed model cohort, no repeated accepted task observations, and no measured variance distribution |
| CI visibility | Conformance CI exists; real-model CI is opt-in | E-001–E-009 and pilot workflows; bounded E-009 real-model workflow with artifact upload | **Partial**: deterministic CI is useful, but no reliable eval score is currently available as a quality gate. Real-model execution is appropriately separate from ordinary PR CI because of cost and duration |
| Promotion of failures to regression cases | Not implemented | E-009 traces and provider responses are retained as short-lived workflow artifacts | **Insufficient**: there is no supported path from a real trace/failure to a permanent eval case |

### Latest E-009 real-model evidence

Run: [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833)  
Run record: `e009-20261117T121839Z-c3c98188`  
Model: `qwen3:8b` through Ollama  
Source revision used by the run: `71a957d1949d4d8bbbeb4267ccaaa0589c8a77ba`

| Measurement | Observed |
|---|---:|
| Status | Failed |
| Duration | 765,073 ms (~12.75 min) |
| Input tokens | 33,714 |
| Output tokens | 1,314 |
| Tool calls | 12 |
| Candidate artifact | Not created |
| First complete service inspection | Successful |
| Existing operations inspected | 6 of 6 |
| Proposal | Accepted by the proposal endpoint, but structurally invalid at validation |
| Validation | Failed with `AN021` (malformed/top-level IR shape) |
| Plan | Not reached |
| Apply | Not called |

The malformed operation used an object for `input`; the contract requires an array of typed input declarations (including `name`, `source`, and `type`). The model repeated the same proposal after receiving the validation diagnostic. The runner then rejected the second successful proposal. This is a model/prompt/repair-loop failure, not a GitHub runner or token-budget failure.

Previous trial progression, as recorded in the project history:
1. Provider-response/tool-call transport issue.
2. Ollama tool-call transport worked, but the model used the display name instead of service ID.
3. Correct service ID, but proposal occurred before all existing operations were inspected.
4. All six operations were inspected, but the 24,000 cumulative input-token budget was exhausted before proposal processing.
5. All six operations were inspected within the 48,000-token budget; malformed IR was proposed and repeated after validation failure.

The older `REPORT.md` still says no live-model trial has occurred, and `research/github-resource-policy.md` still describes trial 5 as in progress. Both statements are stale as of this snapshot.

## 2. E-009 production-dependency audit

| Component | Existing implementation | Missing production property | Assessment |
|---|---|---|---|
| Crash recovery | File-backed SQLite work store; expiring job/relay leases; monotonic fencing tokens; retry and outbox/inbox crash-point tests; durable records survive database reopen | Process supervision, automatic restart policy, bounded worker termination/escalation, operational recovery procedures, multi-process/multi-node coordination, clock-skew handling | **Partially present**, not absent |
| State store | SQLite repository and work store share a file-backed database; item/job/outbox/inbox state is persisted; reopen and tenant-isolation tests exist | Production database selection, migrations/rollback, backup/restore, retention, HA, multi-node coordination, schema compatibility policy | **Present as a single-node reference store** |
| Audit logger | E-009 runtime accepts an injected audit sink and fails closed if that sink raises; E-004 policy emits structured decision events | The demo `serve.py` does not wire a durable audit sink; E-004 events are in-memory; no append-only remote store, tamper-evidence, retention, access control, or cross-service correlation | **Critical integration gap**: an audit interface exists, durable audit persistence does not |
| Cost budgeter | E-009 local runner bounds cumulative input/output tokens, tool calls, and wall time; E-007 schema/metrics can record cost and cost per accepted task | No currency-aware per-run/tenant budget, no provider-price registry, no whole-application agent budget, no budget reservation/settlement, no budget enforcement across multiple agents/services | **Partial research-runner budget**, not a production cost-control subsystem |
| Identity and authority | Default-deny capability checks, principal/tenant/capability/resource scopes, trusted identity dependency, declared-effect allowlist | Demo identity is in-memory; no cryptographic grants, workload identity, key rotation, distributed revocation, or production auth integration | **Reference policy only** |
| HTTP and process lifecycle | Bounded stdlib HTTP host, loopback-only demo, body/JSON limits, bounded admission, graceful worker/relay shutdown | Not an internet-facing hardened host; no TLS termination, external process supervisor, production health/readiness/draining, or deployment/upgrade strategy | **Development host only** |
| External effects | Transactional outbox/inbox, at-least-once relay, consumer deduplication, fenced leases | No general external receiver idempotency contract, broker selection, distributed transaction, or remote exactly-once guarantee | **Single-node semantic proof only** |

**Important correction to the initial gap statement:** crash recovery and state persistence are not wholly missing from E-009. They exist at the SQLite job/lease/relay semantic level. The remaining gap is production-grade supervision and multi-node recovery. Similarly, an audit-sink interface exists, but the runnable demo does not connect it to durable storage. The most useful audit improvement is therefore durable, wired persistence—not adding a second abstract audit interface.

## 3. E-007 benchmark status

- Ten task definitions exist in `corpus.json` and `TASKS.md`.
- `trace.schema.json` defines provider-neutral run, candidate, model, task, tool, usage, acceptance, and failure metadata.
- `metrics.py` validates telemetry and aggregates token use, tool calls, repair events, interventions, inference cost, wall time, runtime metrics, acceptance, and cost per accepted task.
- `prepare_workspace.py` materializes one public task without oracle IDs or unrelated task prompts.
- `ORACLE_ISOLATION.md` specifies agent/evaluator trust zones and insists on a disposable OS/container/VM boundary.
- The packager is **not** a sandbox and does **not** execute an agent. The E-007 README and issue #15 explicitly state that no E-007 agent runs or hidden oracles exist.
- The separate pilot already has a provider adapter, trace/finalizer contracts, paired schedule, and statistical analysis, but its CI uses deterministic provider doubles. It is not an independent hidden evaluator and has not generated real-agent acceptance data.
- E-009's Ollama runner is a real-model feasibility harness for one fixed inspect/propose/validate/plan task. It is not an E-007 corpus runner.

Consequently, E-007 is more than an empty benchmark template—it has a task corpus, telemetry model, metrics code, and isolation design—but it is not yet an executable benchmark.

## 4. E-002 decision-evidence audit

The existing `EVALUATION.md` already defines a broad metric set and a sound decision principle: primary metric is total cost per accepted task; security, data integrity, and minimum runtime performance are hard gates; composite scores require published weights and sensitivity analysis. The gap is that no candidate-specific thresholds or weighted scoring rubric have been registered.

The pinned E-002 CI smoke matrix used three randomized repetitions per candidate, 1,000 requests per repetition, concurrency 32, and a trivial in-memory `GET /work?ms=0` workload. Its medians were:

| Candidate | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Sampled CPU (s) | Sampled peak RSS (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| Rust / Tokio + Hyper | 4,009 | 7.271 | 13.344 | 16.035 | 0.10 | 3.92 |
| Elixir / BEAM | 3,751 | 7.880 | 14.374 | 17.307 | 0.29 | 91.89 |
| Go / net/http | 3,707 | 7.984 | 14.425 | 18.689 | 0.16 | 11.90 |
| WASI P2 / Wasmtime 50.0.1 | 3,319 | 8.919 | 16.576 | 19.880 | 0.30 | 28.02 |

These values establish that the four candidates passed the same trivial smoke workload and that the measurement pipeline produced observations. They do **not** establish a winner: hosted-runner noise, only three repetitions, sampled CPU/RSS, missing database/authorization/inter-service workloads, and missing production failure semantics make the data non-decision-grade. The repository explicitly records no runtime decision.

## 5. Threat model and behavioral governance

E-004 is not merely a capability allowlist. It already documents assets, actors, trust boundaries, entry points, abuse cases, human approval gates, and residual risks. Its reference model covers default-deny authorization, principal/tenant/capability/resource scope, expiry, effect allowlists, strict delegation attenuation, path normalization, and structured audit decisions.

The missing layer is **longitudinal governance of agent behavior**:
- No application-level behavioral envelope defines allowed agent trajectories, delegation depth, peer/tool binding, graph evolution, or state transitions over time.
- No orchestrator evaluates a sequence of actions against task intent and evolving risk.
- No durable cross-run/action lineage or trace-level anomaly/drift evaluation exists.
- Human approval gates are documented, but there is no complete trusted checkpoint/resume protocol.
- The runtime cannot yet dynamically attenuate or revoke a running agent's authority in response to behavioral drift.

The IEEE Access paper *Agent-Native Applications: A New Application Paradigm* (Luo and Leon-Garcia, DOI [10.1109/ACCESS.2026.3720448](https://doi.org/10.1109/ACCESS.2026.3720448)) describes a declarative application specification and behavioral envelope, a running application graph, an agent mesh that mediates interactions, an application orchestrator for graph-level control, and a trust layer spanning security, governance, and observability. It also discusses trace-level evaluation, human checkpoints, action lineage, and behavioral drift. E-004/E-009 currently cover parts of the security/authorization boundary, not this full governance architecture.

## 6. Related eval-runner pattern

The external [Agent-Native CI Eval Gate documentation](https://www.agent-native.com/docs/evals/) describes:
- Declarative `*.eval.ts` cases containing input and expected behavior.
- A runner that actually executes the configured agent/model loop.
- Composable deterministic and model-based scorers, each with a threshold.
- A non-zero exit when a scorer misses its threshold.
- JSON output for CI and promotion of a completed trace into a regression case.

The repository has analogous building blocks in separate places, but lacks the integrated case → real agent run → scorer → threshold → CI result path. The file extension and TypeScript API are implementation choices of that external system, not a standard that Agent Native must copy. This repository's current research harness is Python; a Python case format and runner avoid introducing a second runtime merely to imitate syntax.

## 7. Failure patterns and design reversals from branch history

The branch history contains 465 commits. Commit messages, issue records, current source, and experiment notes show the following recurring patterns. Most entries below are evidence-led refinements or corrections, not necessarily reversals of a settled architecture.

| Pattern | Problem observed | Replacement / current approach | Reason evidenced in history |
|---|---|---|---|
| Smoke benchmark → opt-in diagnostic | Early E-002 matrix runs were easy to trigger and could consume disproportionate CI resources | Explicit opt-in benchmark dispatch; normal CI stays conformance-focused | Preserve runner capacity and avoid expensive, noisy measurements on every push |
| Runtime ranking → no premature selection | Three-run shared-runner medians looked like a leaderboard | Keep Go, Rust, WASI P2, and BEAM as open candidates; label smoke data non-decision-grade | Workload and host noise do not justify a runtime decision |
| Public task corpus → protected evaluator boundary | Public task workspace must not reveal hidden tests or oracle identifiers | Separate agent workspace and evaluator trust zones; no sandbox claim until implemented | Prevent benchmark leakage and false acceptance |
| Single trace aggregation → run/candidate identity | Repeated runs and candidate arms could be pooled incorrectly | Add run/candidate/model identity, strict telemetry validation, eligibility, and proposal-hash provenance | Make repeated/paired analysis auditable and preserve infrastructure failures |
| Tool schema exposure → controlled comparison | Progressive discovery and upfront schemas must be compared without changing other variables | Same tool catalog and task; disclosure mode is the isolated variable in a pinned paired schedule | Reduce experimental confounding |
| Cancellation releases capacity → stop acknowledgement | A cancellation request is not proof that the worker has stopped | Keep lease/capacity until worker/supervisor acknowledgement; fence stale workers | Prevent concurrent execution after an unconfirmed stop |
| Best-effort event delivery → explicit at-least-once | A relay can crash after publish but before acknowledgement | Transactional outbox/inbox, fenced leases, retry exhaustion, consumer deduplication | Model duplicate delivery rather than claiming impossible generic exactly-once behavior |
| Loose HTTP/IR parsing → strict boundary validation | Ambiguous encodings, malformed input, and inconsistent runtime parsing can produce divergent behavior | Strict JSON, path/query/header validation, typed inputs, body limits, effect validation | Keep contract/security behavior consistent across implementations |
| Agent may propose immediately → inspect-before-propose | Real Qwen trial proposed without seeing all current operation contracts | Gateway now requires service and every existing operation to be inspected at the same revision | Preserve existing definitions and make proposals grounded in the actual service |
| Small token budget → measured larger budget | Trial 4 exhausted 24k cumulative input tokens just before proposal processing | Trial 5 raised cumulative input allowance to 48k while keeping per-request context at 8,192 | Use measured token consumption rather than arbitrary guesswork |
| Unbounded repair loop → bounded trial | The model can repeat malformed tool calls or repeat proposals | Repeated-invalid-call guard, fixed tool-call/token/wall budgets, fail-closed runner | Keep model failure bounded and observable |

Issues reviewed include #2, #3, #4, #7–#9, #13, and #15–#16; #10–#12 are the corresponding closed E-001–E-003 tracking issues. The issue descriptions confirm the same evidence boundaries: no E-007 hidden evaluator, no production security enforcement, no E-002 runtime decision, and no E-005 mutation path.

## 8. Important metric clarification

It is too broad to say that token cost always grows quadratically with the number of tool calls. If each model request resends an expanding conversation history, the **sum of input tokens across requests can approach quadratic growth** in the number of turns. Actual cost depends on context management, provider prompt caching, incremental APIs, compaction, and the size of tool outputs. Tool-call count alone does not establish quadratic billing. Record raw per-request input/output usage and cached-token usage where available; do not infer cost from call count.

## 9. Research conclusion

1. The most important missing deliverable is an integrated real-agent evaluation loop, not another set of conformance tests.
2. E-007 already has the corpus, trace schema, metrics aggregator, and evaluator-isolation contract. It lacks the actual E-007 execution/evaluation pipeline and independent oracle runtime.
3. E-009 already has a single-node durable state store, job/relay recovery semantics, and an injectable fail-closed audit sink. The urgent production gap is a durable audit sink wired into the runnable service, plus real process supervision and multi-node recovery later.
4. The current Qwen3 trial exposed a specific repair failure: the model does not translate the `AN021` diagnostic into the required input-array shape and repeats the invalid proposal.
5. E-002 has measurements and metrics, but no registered weights or hard thresholds; current smoke results cannot support a technology choice.
6. E-004 has a useful threat model and capability reference model, but no longitudinal behavioral-governance/orchestration layer.
7. The report and resource-policy documents need their real-model evidence snapshots refreshed after the next validation cycle.

**No implementation language, service syntax, runtime substrate, broker, or production database is selected by this audit.**
