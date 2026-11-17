# RPI peer-review checklist

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Purpose:** distinguish implementation verification, real-model observations, and decision-grade evidence.

## E-007 real-agent evaluation

| Review item | Status | Evidence / note |
|---|---|---|
| Eval case excludes scorer implementation and hidden oracle identifiers | Pass | Case/scorers stay runner-side; the model receives the task and Gateway surface |
| Runner invokes a real model and live E-009 Gateway | Pass (implementation) | `eval_runner.py` calls `local_agent.py`, Ollama, and the E-009 Gateway |
| Every repetition has a distinct run identity and retained trace | Pass (implementation) | Unique eval/run directories and raw JSONL retained in the Actions artifact |
| Candidate/proposal/validation/plan provenance is checked | Pass (scorer implementation) | Deterministic scorer checks exact proposal/candidate hash continuity; the three-run real cohort produced no candidate to pass it |
| Three deterministic scorers and thresholds are explicit | Pass | Contract, lifecycle, and behavioral-safety scorers all require 1.0 |
| Provider usage is recorded without inferring missing counts | Pass (implementation) | Per-request Ollama token usage is captured and validated |
| Failure taxonomy inspects nested validation diagnostics | Pass (implementation) | Classifier reads both outer diagnostics and nested `result.diagnostics`; E-007 tests pass |
| Aggregate token/time/cost budget fails fast | Pass (mock) | Mock runner executes one run, then records two repetitions as not started when the next reservation exceeds the aggregate input budget; budget stops use a separate resource category |
| E-009 task now defines complete IR snapshot semantics | Pass (contract/tests) | `ir_version`, full service/types/operations, array inputs, and semantic `result.valid` behavior documented and published in tool schema |
| Plan is blocked without a valid matching proposal hash | Pass (implementation/tests) | E-009 returns `VALIDATION_REQUIRED` before forwarding a premature/mismatched plan to the Gateway |
| Corrected real-model outcome | **Fail — not accepted** | Workflow [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547), artifact [14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550): 3/3 Qwen3 attempts failed at validation with `AN021`; no validated plan or candidate |
| Independence of three model runs | **Not established** | All used temperature 0 and seed 42; per-request usage and tool traces matched. Ollama logs show prompt/KV cache reuse. Treat as deterministic failure reproduction, not independent statistical samples |
| Post-fix deterministic cohort | **Fail / 0 accepted** | Run [44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), artifact [14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630), used temperature 0.7/seed 20261117; the model produced full top-level IR but rewrote five existing operations, then hit wall ceiling after inspecting all six; no second proposal, validate, or plan |

| Current real-model compliance | **Open** | Complete-IR schema, AN021 hint, corrected prompt/task, same-hash plan gate, and budget taxonomy still need an artifact showing exact preservation, successful validation, safe plan, and no apply |

| Post-fix stochastic probe | **Fail — exploratory only** | [Run 44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), [artifact 14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630): complete top-level IR and array inputs, but five existing operations rewritten; inspection gate then followed, but no corrected resubmission before wall-time failure |
| Wall-time/provider classification | Pass (deterministic test) | E-007 run [44123795574](https://github.com/mojtaba-arvin/agent-native/actions/runs/44123795574) verifies provider transport failure at the configured max-wall boundary is also classified as `resource_budget_exceeded`, not just as an agent failure |

## E-005 interface and E-009 kernel

| Review item | Status | Evidence / note |
|---|---|---|
| Complete proposed IR schema is published | Pass | E-005 tool schema requires `ir_version`, `service`, `types`, and `operations`; nested operation inputs are arrays of declarations |
| AN021 includes actionable repair guidance | Pass (implementation/tests) | Missing or malformed top-level IR receives a fix hint explaining full-snapshot semantics |
| Plan requires successful validation of the same hash | Pass (implementation/tests) | E-009 runner gate checks `result.valid=true` and exact proposal hash |
| Durable audit records persist before handlers and survive reopen | Pass | SQLite integration tests cover allow/deny, reopen, fail-closed, and concurrent append |
| Application update/delete attempts are blocked | Pass (defense in depth) | SQLite triggers reject update/delete; not cryptographic tamper-proofing |
| Audit store failure prevents handler execution | Pass | Integration test verifies fail-closed service response |
| E-005 interface suite | Pass | 17 tests pass in CI [44102058544](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058544) |
| E-009 suite | Pass | 76 tests pass in CI [44106101942](https://github.com/mojtaba-arvin/agent-native/actions/runs/44106101942) |

## E-002 runtime decision evidence

| Review item | Status | Evidence / note |
|---|---|---|
| Weights and provisional gates registered before the ten-run matrix | Pass | Matrix protocol and thresholds were committed before run [44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181) |
| Comparable request mix and run protocol | Pass | Four candidates; 10 repetitions × 5,000 requests, concurrency 32, warm-up 250, randomized order |
| Raw runs and distributions retained | Pass | 40 run summaries plus request-level JSONL in the 14-day artifact |
| Functional, p99, throughput, RSS, and startup screens | Pass | All candidates passed these measured screens |
| CPU threshold's product provenance | **Open** | 0.5 s/5,000 requests is pre-registered but not derived from a documented product SLO/capacity/cost target; see [CPU analysis](../experiments/e002/cpu-gate-analysis.md) |
| CPU result | Diagnostic | All four candidates exceeded the provisional screen; this is not a basis for post-hoc threshold change or a runtime choice |
| Ecosystem/operability score | Not measured | Evidence rubric exists; candidate scoring is absent |
| Injected failure semantics | Not measured | Required assertions are documented but not run comparably across all candidates |
| Comparable deployable artifact size | Not measured | Packaging/equivalence protocol exists; measurements are absent |
| Final weighted ranking/runtime selection | Not performed | Correctly deferred |

## Overall review decision

- [x] Research, plan, evidence index, and design-decision log exist.
- [x] E-009 durable audit implementation is integrated and passes CI.
- [x] E-005 complete-IR schema and AN021 guidance pass deterministic tests.
- [x] E-007 aggregate budget reservation and mock fail-fast behavior pass deterministic tests.
- [x] E-002 ten-run diagnostic data is published without selecting a runtime.
- [ ] Re-run Qwen3 after the complete-IR and validation-gate corrections.
- [ ] Verify the model produces `ir_version=1` and all existing operations plus the requested operation; inspect the resulting artifact before closing E-007 validation.
- [ ] Resolve E-002 CPU-gate provenance from a product capacity/cost model and measure fault injection/ecosystem/artifact-size criteria before any decision-grade matrix.

**Cycle status:** partially validated. Implementation and diagnostic evidence have advanced, but E-007 real-agent acceptance is still negative and post-fix model behavior is unknown. E-002 remains diagnostic. Do not declare the RPI cycle complete or choose a runtime yet.
