# Evidence index

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Rule:** every artifact is classified by what it can support. “Diagnostic” and “initial” do not imply a production decision or statistical claim.

## E-002 — Runtime-substrate comparison

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Ten-repetition matrix | [Workflow 44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181); [committed result](../experiments/e002/results/2026-11-17-ten-run-diagnostic.md) | **Diagnostic** | 10 randomized runs × 5,000 requests per Go, Rust, WASI P2, and BEAM candidate; run-level distributions; all functional checks passed; all four exceed the provisional CPU screen | Shared hosted runner, trivial in-memory workload; ecosystem rubric, fault injection, and comparable artifact sizes not measured; CPU threshold not derived from a product SLO |
| CPU gate interpretation | [CPU analysis](../experiments/e002/cpu-gate-analysis.md) | **Diagnostic analysis** | Converts the registered 0.5 s/5k screen into per-request CPU cost and documents its missing product-side provenance and measurement caveats | No revised threshold, optimization mandate, or runtime choice |

**E-002 conclusion:** no final weighted score and no runtime selected.

## E-007 — Real-agent evaluation

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Corrected three-run Qwen3 execution | [Workflow 44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547); [artifact 14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550) | **Initial / deterministic failure reproduction** | Three Qwen3/Ollama task attempts reached proposal validation; all failed with `AN021`; raw per-run tool traces and provider token diagnostics retained for 14 days | `temperature=0`, fixed seed 42, prompt cache reused, one task only; no successful validation/plan, no independent statistical observations, no broad corpus/model cohort |
| Deterministic runner and scoring tests | [E-007 workflow 44102058506](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058506) | **Implementation verification** | 42 E-007 tests pass, including duplicate proposal lifecycle, nested failure taxonomy, and mock aggregate-budget fail-fast | Mocked control-flow tests are not real-model acceptance |
| E-005 schema and diagnostic tests | [E-005 workflow 44102058544](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058544) | **Implementation verification** | 17 E-005 interface tests pass, including complete IR schema publication and AN021 fix-hint behavior | Does not demonstrate model compliance |
| E-009 runner and kernel tests | [E-009 workflow 44102058563](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058563) | **Implementation verification** | 75 E-009 tests pass, including fail-closed plan gating | Does not demonstrate real-model repair after AN021 |

**E-007 conclusion:** not accepted. The model correctly used an input declaration array, but submitted a partial IR snapshot with no `ir_version` and only the new operation. It then called plan after `result.valid=false`; the original runner did not prevent this. The latest code/schema fixes require a new real-model run before reassessment.

## E-009 — Integrated kernel

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Durable authorization audit sink | [E-009 workflow 44102058563](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058563), 75-test suite | **Implementation verification** | SQLite audit persistence, reopen, concurrency, append-only triggers, fail-closed behavior, plus local-agent provenance and plan-gate coverage | Single-node demo; not tamper-proof, remotely replicated, or production-ready |
| IR proposal contract | [IR contract](../experiments/e009/ir-contract.md) | **Design contract** | Complete-snapshot vs patch semantics and correct validation-result handling | Real model must still demonstrate compliance |

## Cross-cutting decisions and limitations

- [Design decisions](./design-decisions.md) records the cache/determinism finding, IR snapshot contract, validation gate, budgeter behavior, nested diagnostic classification, and CPU-gate provenance.
- Three deterministic repetitions are not independent model samples and are not statistical model evidence.
- No runtime has been selected.
- The E-007 artifact contains private runner traces and is short-retention evidence; only compact findings and provenance are committed.
- The current ten-task E-007 corpus and one Qwen3 model do not support general benchmark claims. Broader model/corpus design remains future work.
