# RPI Research — Evidence Audit

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**E-007 artifact source revision:** `1596d595e040267279324aafb7542213b9f31d89` · Subsequent deterministic fixes are indexed in [evidence-index.md](evidence-index.md).  
**Scope:** evidence-only audit. No source code, runtime architecture, or technology selection is changed by this document.

## Executive finding

E-007 now has a specialized real-agent runner for one fixed E-009 inspect/propose/validate/plan task, three deterministic scorers, raw trace preservation, strict usage telemetry, aggregate token/time budget reservation, and mock-tested fail-fast behavior. The corrected three-run Qwen3 execution [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547), artifact [14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550), is **not accepted**: all three attempts reached validation and failed with `AN021`. The new operation's `input` was already the correct declaration array; the submitted IR omitted `ir_version=1` and all existing operations. The model then called plan despite `result.valid=false`. All three used temperature 0 and seed 42, with matching token counts/tool paths; Ollama logs show prompt/KV cache reuse. This is a deterministic failure reproduction, not three independent statistical samples.

The earlier standalone E-009 Qwen3 run [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833) is separate: in that trial the input was an object. Do not conflate it with the later E-007 artifact, where input was an array but the top-level snapshot was incomplete.

A separate one-run stochastic probe, [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), artifact [14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630), used temperature 0.7 and seed 20261117. It produced a complete top-level IR (`ir_version=1`, service, types, seven operations) with array-shaped inputs, but changed five of the six existing operation declarations. Its first proposal was rejected before validation with `INSPECTION_INCOMPLETE`; after the model inspected all six existing operations, it did not submit a second proposal before the 900-second wall budget ended. The final provider request returned HTTP 500/cancelled at the wall-time boundary. No validate or plan was reached. The run consumed 44,377 input and 1,399 output tokens; local inference currency cost remains unpriced. This is one exploratory stochastic observation, not a statistical sample or a successful post-fix evaluation.

## 1. Evaluation-loop gap audit

| Required evaluation criterion | Current state | Existing evidence | Gap / sufficiency |
|---|---|---|---|
| Public task definitions | Implemented | E-007 contains 10 task statements spanning CRUD, schema evolution, tenancy, idempotency, deadlines, streaming, durable recovery, security, debugging, and safe planning | **Sufficient for a first public corpus**, not sufficient as a complete benchmark distribution |
| Agent execution runner | Implemented for one fixed task | E-007 `eval_runner.py` invokes the real `local_agent.py`/Ollama adapter and live E-009 Gateway; traces/candidates are preserved and scored | **Narrow scope**: not a generic runner for all ten tasks and not a sandbox |
| Real-model execution evidence | One deterministic three-run failure cohort plus one stochastic exploratory failure | Qwen3 E-007 runs [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547) (3/3 AN021) and [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141) (one incomplete/preservation-invalid proposal path and wall timeout) | **No accepted task or successful validate/plan**; stochastic probe shows variation but is one non-statistical observation |
| Independent acceptance oracle | Contract designed, implementation absent | `experiments/e007/ORACLE_ISOLATION.md`; pilot finalizer/evaluator-result contract; E-009 local candidate verifier | **Insufficient**: public E-007 has no private oracle package or separate evaluator execution boundary. E-009's verifier is trusted runner-side validation of one fixed proposal, not a hidden benchmark oracle |
| Scorers | Implemented for first eval case | Declarative E-007 case and three deterministic binary scorers for candidate contract, proposal lifecycle, and behavioral safety; each threshold is 1.0 | **Task-specific**: no general scorer registry or independent hidden oracle for arbitrary tasks |
| Trace and usage telemetry | Implemented as schemas/aggregators and pilot wiring | E-007 trace schema and strict aggregator; pilot provider-usage path and provenance checks; E-009 provider-reported token counts | **Sufficient foundations**, but real-run data is sparse and incomplete as a benchmark corpus |
| Failure classification | Implemented in parts | E-007 distinguishes invalid tool calls, schema errors, business tool errors, and ineligible infrastructure failures; pilot finalizer preserves failed/interrupted runs | **Sufficient foundations**, but the five E-009 model failures need a common durable result taxonomy and analysis |
| Repetition and statistical analysis | Insufficient | Three temperature-zero/fixed-seed E-007 attempts match in usage/tool path; Ollama logs show prompt/KV prefix-cache reuse | **Not independent samples**; no model variance or statistical claim supported |
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

### E-007 three-run Qwen3 artifact — inspected result

Run: [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547) · artifact ID `14332334550` · source revision `1596d595e040267279324aafb7542213b9f31d89` · model `qwen3:8b` via Ollama.

| Attempt | Outcome | Failure stage | Input / output tokens | Duration | Currency cost | Classification |
|---|---|---|---:|---:|---|---|
| 1 | Failed | `service.validate` · `AN021` | 35,984 / 1,602 | 894.95 s | Not priced (local Ollama) | Schema incompatibility; validation rejection |
| 2 | Failed | `service.validate` · `AN021` | 35,984 / 1,602 | 843.78 s | Not priced (local Ollama) | Same deterministic failure path |
| 3 | Failed | `service.validate` · `AN021` | 35,984 / 1,602 | 844.69 s | Not priced (local Ollama) | Same deterministic failure path |

The operation `input` was an array of `name`/`source`/`type` declarations. The proposal omitted `ir_version` and included only the new operation. The canonical validator requires exactly `ir_version`, `service`, `types`, and `operations`; that explains `AN021`, while omission of existing operations would separately fail preservation. The response had outer `ok=true` but `result.valid=false`; the model then called plan, and the Gateway returned another invalid no-mutation plan. The provider diagnostics show a final assistant response of 1,437 content characters after that plan, but the old runner did not retain its body. The trace contains no later corrected proposal, so we cannot inspect the final text or claim whether it formulated a correction internally; it did not submit a second corrected proposal. The successful-proposal repair budget was not exhausted, although each run approached the 900-second wall ceiling.

All attempts used temperature 0 and seed 42 and had matching token counts/tool paths. Ollama logs show prompt/KV prefix-cache reuse, not response-cache replay. Treat these as deterministic reproductions, not independent statistical samples. The earlier standalone E-009 run [44081733833](https://github.com/mojtaba-arvin/agent-native/actions/runs/44081733833) is a separate case where the input member was an object.

## 2. E-009 production-dependency audit

| Component | Existing implementation | Missing production property | Assessment |
|---|---|---|---|
| Crash recovery | File-backed SQLite work store; expiring job/relay leases; monotonic fencing tokens; retry and outbox/inbox crash-point tests; durable records survive database reopen | Process supervision, automatic restart policy, bounded worker termination/escalation, operational recovery procedures, multi-process/multi-node coordination, clock-skew handling | **Partially present**, not absent |
| State store | SQLite repository and work store share a file-backed database; item/job/outbox/inbox state is persisted; reopen and tenant-isolation tests exist | Production database selection, migrations/rollback, backup/restore, retention, HA, multi-node coordination, schema compatibility policy | **Present as a single-node reference store** |
| Audit logger | E-009 has a SQLite audit sink wired into `serve.py`; allow/deny decisions persist before handlers and fail closed on storage errors | No remote replication, retention service, external ACL, or cryptographic tamper-evidence | **Implemented for the single-node reference service**, not production audit infrastructure |
| Cost budgeter | E-009 has per-run ceilings; E-007 has aggregate token/time reservation and mock-tested fail-fast; optional priced-token budgets are supported | No production tenant/application budget or multi-agent reservation/settlement; local Ollama tariff is not configured | **Research-runner control only**; local inference currency cost is unpriced, not zero |
| Identity and authority | Default-deny capability checks, principal/tenant/capability/resource scopes, trusted identity dependency, declared-effect allowlist | Demo identity is in-memory; no cryptographic grants, workload identity, key rotation, distributed revocation, or production auth integration | **Reference policy only** |
| HTTP and process lifecycle | Bounded stdlib HTTP host, loopback-only demo, body/JSON limits, bounded admission, graceful worker/relay shutdown | Not an internet-facing hardened host; no TLS termination, external process supervisor, production health/readiness/draining, or deployment/upgrade strategy | **Development host only** |
| External effects | Transactional outbox/inbox, at-least-once relay, consumer deduplication, fenced leases | No general external receiver idempotency contract, broker selection, distributed transaction, or remote exactly-once guarantee | **Single-node semantic proof only** |

**Important correction to the initial gap statement:** crash recovery and state persistence are not wholly missing from E-009. They exist at the SQLite job/lease/relay semantic level. The remaining gap is production-grade supervision and multi-node recovery. Similarly, an audit-sink interface exists, but the runnable demo does not connect it to durable storage. The most useful audit improvement is therefore durable, wired persistence—not adding a second abstract audit interface.

## 3. E-007 benchmark status

- Ten public task definitions exist in `corpus.json` and `TASKS.md`; these are a starting corpus, not broad benchmark coverage.
- `trace.schema.json` and `metrics.py` provide provider-neutral event validation and aggregation for tokens, tool calls, repairs, interventions, inference cost, wall time, runtime metrics, acceptance, and cost per accepted task.
- `prepare_workspace.py` materializes one public task without oracle IDs or unrelated task prompts. It is a packager, not a sandbox or agent runner.
- `ORACLE_ISOLATION.md` defines evaluator trust boundaries, but a generic isolated hidden-oracle runner is not implemented.
- E-007 now has a specialized executable case/runner for one fixed E-009 Gateway task, three deterministic scorers, raw provider/tool traces, nested validation-diagnostic taxonomy, and aggregate token/time reservation. CI verifies the implementation; the real-model cohort was 0/3 accepted.
- The model's new operation input array was correctly shaped. The missing top-level `ir_version` and existing operations caused the complete-snapshot contract violation. The model then called plan despite `result.valid=false`.
- The original three-run cohort used `temperature=0`, `seed=42`; matching token counts/tool paths and Ollama logs show prompt/KV cache reuse. It is a deterministic failure reproduction, not independent statistical evidence.
- One exploratory run at temperature 0.7/seed 20261117 generated the complete top-level IR shape, but rewrote five existing operations and timed out at the 900-second wall ceiling after being guided to inspect all operations. It did not resubmit a corrected proposal or reach validation/plan. This demonstrates a changed behavioral path, not success or statistical superiority.
- The runner taxonomy now preserves the provider-transport cause while additionally flagging resource-budget exhaustion when a run reaches its configured wall ceiling.
- A three-tier cohort and broader 30-task design is only future work in [e007-future-evaluation-plan.md](e007-future-evaluation-plan.md). It has not been executed.
- The separate E-005 pilot's protocol CI uses deterministic provider doubles; this is wiring evidence, not real-model evaluation.

E-007 is now an **executable single-case real-agent harness**, not a full ten-task benchmark or an independent hidden-oracle evaluation system.

## 4. E-002 decision-evidence audit

The E-002 matrix has pre-registered weights/gates and ten randomized repetitions per candidate, 5,000 requests per repetition, concurrency 32, and warm-up 250. It completed [workflow 44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181); the [ten-run diagnostic](../experiments/e002/results/2026-11-17-ten-run-diagnostic.md) contains distributions and partial contributions.

All candidates passed functional, p99, throughput, RSS, and startup screens, but all failed the provisional CPU screen:

| Candidate | Mean CPU s / 5,000 | CPU ms / request | Gate |
|---|---:|---:|---|
| Rust / Tokio + Hyper | 0.687 | 0.1374 | Fail |
| Go / net/http | 1.092 | 0.2184 | Fail |
| Elixir / BEAM | 1.917 | 0.3834 | Fail |
| WASI P2 / Wasmtime 50.0.1 | 1.949 | 0.3898 | Fail |

The 0.5 s threshold was pre-registered but is not traceable to a product SLO, vCPU capacity target, or deployment-cost model. It equals 0.1 ms CPU/request (10,000 requests per CPU-second), stricter than all observed means. CPU accounting uses process-tree `/proc` snapshots at the start/end of the batch; the 20 ms monitor is used for RSS, not CPU, leaving a possible short-lived-child accounting gap. Do not revise the gate retrospectively or treat it as a validated product requirement. A future threshold must be derived from a documented capacity/cost model before a new run. See [CPU gate analysis](../experiments/e002/cpu-gate-analysis.md).

A second ten-repetition matrix completed in [workflow 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511). All four candidates again passed 10/10 functional runs and again failed the CPU gate. That workflow also measured uncompressed Linux x86_64 deployment payloads, including resolved shared ELF dependencies: Go 10,012,310 B (9.55 MiB), Rust 4,991,320 B (4.76 MiB), WASI P2 + Wasmtime 71,947,386 B (68.61 MiB), and BEAM release + ERTS 74,856,626 B (71.39 MiB). Package models differ; these are host-specific payload estimates, not directly comparable portable package/container sizes.

Artifact size is now measured once per candidate under this explicit method. Ecosystem/operability and comparable injected failure semantics remain not measured. The 0.5 CPU-second threshold has no documented product capacity/cost provenance and was failed by all candidates in both cohorts. No complete weighted score or runtime selection is justified; E-002 remains diagnostic. See [second-pass report](../experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md).

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

The repository now has an analogous **specialized single-case** path: declarative E-007 JSON case → real Qwen3/Ollama execution through E-009 Gateway → three deterministic scorers → threshold check → non-zero CI result and raw evidence artifact. The implementation is in `experiments/e007/eval_runner.py` and the case is `experiments/e007/evals/e009-readonly-proposal.eval.json`. It is not yet a generic runner for all ten public tasks, and it does not provide a general isolated hidden-oracle/sandbox execution environment. The file extension and TypeScript API are implementation choices of the external system, not a standard Agent Native must copy. The repository's research harness remains Python to avoid a second runtime for syntax imitation.

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

1. E-007 has an executable real-agent runner for one fixed E-009 task. The deterministic three-run Qwen3 cohort failed 0/3 with AN021; the one stochastic post-fix probe also failed to complete a valid proposal/validate/plan cycle.
2. The deterministic cohort submitted a partial IR missing `ir_version=1` and existing operations, then attempted plan despite `result.valid=false`.
3. The stochastic probe generated a complete top-level IR with array inputs, but rewrote five existing operation contracts, was blocked at the inspect-all gate, and hit the wall-time ceiling before submitting a second proposal.
4. The E-005 full-IR tool schema, AN021 fix hint, E-009 task/prompt and same-hash plan gate, candidate-preservation path, and E-007 wall-budget taxonomy are implemented and covered by deterministic tests. No post-Gateway-preservation real-model success has been demonstrated. A one-run deterministic probe with temperature 0, seed 42 and a 1,200-second wall ceiling is running in [workflow 44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813); its artifact is not yet evidence until independently inspected.
5. Aggregate token/time budgets fail fast before an unaffordable next repetition; local Ollama currency cost is retained as unknown. These are research-runner controls, not a production multi-agent cost service.
6. Three fixed-seed temperature-zero attempts are deterministic failure reproductions; the single nonzero-temperature probe is only exploratory. No statistical or model superiority claim is supported.
7. E-002's ten-run shared-host data is diagnostic. The 0.5 CPU-second gate has no demonstrated product-capacity origin; ecosystem, fault injection and the newly added artifact-size measurement have not yet been measured in the matrix. No runtime is selected.
8. E-009's durable audit sink and fail-closed plan control are tested as a single-node reference implementation, not a production security/audit architecture.

**No implementation language, service syntax, runtime substrate, broker, production database, or transport is selected by this audit.**

### Latest validation implementation status

- E-007: 48 deterministic tests passed in workflow [44145390001](https://github.com/mojtaba-arvin/agent-native/actions/runs/44145390001), including distinct timeout, provider HTTP, transport, and explicit OOM classifications. A one-run deterministic post-Gateway-preservation Qwen3 trial is in progress in [workflow 44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813); it is not yet reviewed or accepted.
- E-009: 80 tests passed in workflow [44128413303](https://github.com/mojtaba-arvin/agent-native/actions/runs/44128413303), including exact inspected-operation preservation preflight, fail-closed plan gate, candidate retention before verification, and a bounded proposal-attempt budget.
- E-002: 9 Python tests for matrix/artifact measurement passed as part of workflow [44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511); two 10×5,000 shared-host diagnostic cohorts show all four candidates above the provisional CPU screen. The second cohort measured one host-specific deployable payload per candidate. CPU-gate provenance analysis now covers both cohorts; the threshold still has no product-capacity basis. Ecosystem and injected-failure comparisons remain open.

## 10. Evidence and decisions

- [Design decisions](design-decisions.md) records deterministic/cache findings, complete IR semantics, validation gating, aggregate budget behavior, nested failure taxonomy, and CPU-gate provenance.
- [Evidence index](evidence-index.md) classifies E-002/E-007/E-009 artifacts as diagnostic, initial, or implementation-verification evidence.
- [Future E-007 evaluation plan](e007-future-evaluation-plan.md) describes a multi-tier, broader-corpus experiment as future work only; it has not been executed.
- [E-009 IR contract](../experiments/e009/ir-contract.md) defines full-snapshot proposal semantics and validation-result handling.
