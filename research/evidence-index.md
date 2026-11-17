# Evidence index

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Rule:** every artifact is classified by what it can support. “Diagnostic” and “initial” do not imply a production decision or statistical claim.

## E-002 — Runtime-substrate comparison

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Ten-repetition matrices | [First workflow 44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181); [second workflow 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511); [first result](../experiments/e002/results/2026-11-17-ten-run-diagnostic.md); [second result + package sizes](../experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md) | **Diagnostic** | Two randomized cohorts of 10 × 5,000 requests/candidate; all 10/10 functional runs passed; both cohorts show all four candidates exceed the provisional CPU screen. Second cohort measured Linux x86_64 payload totals: Go 10,012,310 B; Rust 4,991,320 B; WASI+Wasmtime 71,947,386 B; BEAM release 74,856,626 B | Shared hosted runner and trivial in-memory workload; ecosystem rubric and comparable fault injection not measured; package models are host-specific and differ; CPU threshold not derived from a product SLO |
| CPU gate interpretation | [CPU analysis](../experiments/e002/cpu-gate-analysis.md) | **Diagnostic analysis** | Converts the registered 0.5 s/5k screen into per-request CPU cost and documents its missing product-side provenance and measurement caveats | No revised threshold, optimization mandate, or runtime choice |

**E-002 conclusion:** no final weighted score and no runtime selected.

## E-007 — Real-agent evaluation

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Corrected three-run Qwen3 execution | [Workflow 44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547); [artifact 14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550) | **Initial / deterministic failure reproduction** | Three Qwen3/Ollama task attempts reached proposal validation; all failed with `AN021`; raw per-run tool traces and provider token diagnostics retained for 14 days | `temperature=0`, fixed seed 42, prompt cache reused, one task only; no successful validation/plan, no independent statistical observations, no broad corpus/model cohort |
| Deterministic runner and scoring tests | [E-007 workflow 44123795574](https://github.com/mojtaba-arvin/agent-native/actions/runs/44123795574) | **Implementation verification** | 44 E-007 tests pass, including duplicate proposal lifecycle, nested failure taxonomy, mock aggregate-budget fail-fast, and provider failure at wall-budget classification | Mocked control-flow tests are not real-model acceptance |
| Post-fix stochastic Qwen3 probe | [Workflow 44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141); [artifact 14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630); [analysis](../experiments/e007/results/2026-11-17-stochastic-qwen3-probe.md) | **Exploratory / ineligible** | At temperature 0.7, model produced IR with ir_version=1, seven operation entries, and array-shaped inputs; it followed INSPECTION_INCOMPLETE by inspecting all six existing operations | First proposal was blocked before validation; it rewrote five existing contracts, never submitted a second proposal, then hit the 900s wall ceiling with provider transport failure; no validate/plan and no accepted task |
| E-005 schema and diagnostic tests | [E-005 workflow 44102058544](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058544) | **Implementation verification** | 17 E-005 interface tests pass, including complete IR schema publication and AN021 fix-hint behavior | Does not demonstrate model compliance |
| E-009 runner and kernel tests | [E-009 workflow 44106101942](https://github.com/mojtaba-arvin/agent-native/actions/runs/44106101942) | **Implementation verification** | 76 E-009 tests pass, including fail-closed plan gating | Does not demonstrate real-model repair after AN021 |

**E-007 conclusion:** not accepted. The deterministic cohort submitted partial IR (missing `ir_version` and existing operations) and attempted plan after `result.valid=false`. The stochastic probe produced a complete top-level seven-operation IR, but rewrote five existing contracts, was rejected at the inspect-all gate before validation, and ended at the wall-time ceiling before a second proposal. Neither run demonstrates a successful validate/plan cycle.

## E-009 — Integrated kernel

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Durable authorization audit sink | [E-009 workflow 44106101942](https://github.com/mojtaba-arvin/agent-native/actions/runs/44106101942), 76-test suite | **Implementation verification** | SQLite audit persistence, reopen, concurrency, append-only triggers, fail-closed behavior, plus local-agent provenance and plan-gate coverage | Single-node demo; not tamper-proof, remotely replicated, or production-ready |
| IR proposal contract | [IR contract](../experiments/e009/ir-contract.md) | **Design contract** | Complete-snapshot vs patch semantics and correct validation-result handling | Real model must still demonstrate compliance |

## Cross-cutting decisions and limitations

- [Design decisions](./design-decisions.md) records the cache/determinism finding, IR snapshot contract, validation gate, budgeter behavior, nested diagnostic classification, and CPU-gate provenance.
- Three deterministic repetitions are not independent model samples and are not statistical model evidence.
- No runtime has been selected.
- The E-007 artifact contains private runner traces and is short-retention evidence; only compact findings and provenance are committed.
- The current ten-task E-007 corpus and one Qwen3 model do not support general benchmark claims. Broader model/corpus design remains future work.
