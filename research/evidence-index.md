# Evidence index

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Rule:** every artifact is classified by what it can support. Diagnostic and initial evidence do not imply a production decision or statistical claim.

## E-002 — Runtime-substrate comparison

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Two ten-repetition matrices | [First workflow 44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181); [second workflow 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511); [first result](../experiments/e002/results/2026-11-17-ten-run-diagnostic.md); [second result + package sizes](../experiments/e002/results/2026-11-17-second-ten-run-artifact-diagnostic.md) | **Diagnostic** | Two randomized cohorts of 10×5,000 requests/candidate; all 10/10 functional runs passed. Both cohorts show all four candidates exceed the provisional CPU screen. Second cohort measured Linux x86_64 uncompressed payloads: Go 10,012,310 B; Rust 4,991,320 B; WASI+Wasmtime 71,947,386 B; BEAM release+ERTS 74,856,626 B | Shared hosted runner and trivial in-memory workload; package shapes differ; ecosystem rubric and comparable fault injection remain unmeasured; CPU threshold not derived from a product SLO |
| CPU gate interpretation | [CPU analysis](../experiments/e002/cpu-gate-analysis.md) | **Diagnostic analysis** | Converts registered 0.5 s/5k screen into per-request CPU cost; identifies missing product-side provenance and measurement limitations | No product capacity/cost requirement has yet justified this threshold; no revised threshold or runtime choice |
| Artifact-size protocol and result | [Workflow 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511); [artifact 14347795200](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511/artifacts/14347795200) | **Initial / host-specific measurement** | One Linux x86_64 uncompressed deployment-payload size per candidate, with per-file hashes and resolved ELF dependencies | Not equivalent portable package/container sizes; no compressed image/base OS measurement; not sufficient for a final ranking |

**E-002 conclusion:** no complete weighted score and no runtime selected. Both CPU cohorts fail the hard screen. Artifact size has been measured once; ecosystem/operability and comparable fault injection remain open.

## E-007 — Real-agent evaluation

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Corrected three-run Qwen3 cohort | [Workflow 44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547); [artifact 14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550) | **Initial / deterministic failure reproduction** | 3/3 Qwen3 attempts reached validation and failed with AN021; the new operation input array was correct, but top-level ir_version and existing operations were omitted; model attempted plan after result.valid=false | Temperature0/fixed seed42 and prompt/KV cache reuse mean these are deterministic reproductions, not independent statistical samples; no successful validation/plan |
| Deterministic runner/scorer tests | [Workflow 44126229777](https://github.com/mojtaba-arvin/agent-native/actions/runs/44126229777) | **Implementation verification** | 45 E-007 tests, including nested diagnostics, preservation/validation/repair-budget taxonomy, and aggregate budget fail-fast | Mock control-flow tests are not real-model acceptance |
| Stochastic post-fix Qwen3 probe | [Workflow 44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141); [artifact 14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630); [analysis](../experiments/e007/results/2026-11-17-stochastic-qwen3-probe.md) | **Exploratory / ineligible** | At temp0.7 the model produced a top-level IR with ir_version, seven operations, and array inputs; after INSPECTION_INCOMPLETE it inspected all six existing operations | Attempted full IR rewrote five existing operations; first proposal was blocked before validation; no corrected second proposal before 900s wall timeout; no validate/plan |
| Post-Gateway-preservation deterministic trial | [Workflow 44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813); artifact pending | **Awaiting real-model evidence** | One Qwen3 run, temperature 0 / seed 42, complete-IR task, Gateway-owned exact base-preservation enforcement, bounded proposal attempts and candidate retention; 1,200s wall cap | Workflow was running at snapshot; no acceptance or failure conclusion until raw artifact and Ollama logs are inspected |
| Future model/task cohort | [Future evaluation plan](e007-future-evaluation-plan.md) | **Future work only** | Defines a broader 30-task, three-model-tier, varied-seed plan and sample-size/power considerations | Not executed; no multi-tier model comparison or confirmatory statistics |

**E-007 conclusion:** not accepted. Neither deterministic nor stochastic real-model trials completed a valid proposal → validate → safe plan cycle. A post-fix real-model artifact after Gateway-owned preservation enforcement remains required.

## E-009 — Integrated kernel and Agent Gateway

| Evidence | Location | Classification | What it supports | What remains open |
|---|---|---|---|---|
| Durable authorization audit sink | [E-009 workflow 44128413303](https://github.com/mojtaba-arvin/agent-native/actions/runs/44128413303), 80-test suite | **Implementation verification** | SQLite audit persistence, reopen, concurrency, append-only triggers, fail-closed behavior, semantic plan gating, Gateway base-preservation checks, bounded proposals and candidate retention | Single-node reference service; not remotely replicated, cryptographically tamper-evident or production-ready |
| Complete IR proposal contract | [IR contract](../experiments/e009/ir-contract.md) | **Design contract** | Complete snapshot rather than patch; exact base preservation in E-009 Gateway; semantic validation-result requirements | Real model must still produce an exact snapshot and finish validation/plan |

## Cross-cutting decisions and limitations

- [Design decisions](design-decisions.md) records cache/determinism, complete IR, exact preservation, validation gates, repair budget, budgeter semantics, and CPU-gate provenance.
- [Peer-review checklist](peer-review-checklist.md) distinguishes deterministic CI, real-model observations, and still-open acceptance.
- Three fixed-seed temperature-zero attempts are deterministic failure reproductions; the single non-zero-temperature probe is one exploratory observation, not a statistical comparison. The post-Gateway-preservation deterministic trial (44144939813) is in progress and is not evidence until its artifact is reviewed.
- The E-007 aggregate token/time budget and wall-limit taxonomy are runner-level controls. Local Ollama currency cost remains unpriced, not zero.
- No runtime has been selected; no production-readiness, model-superiority, or Agent Native productivity claim is supported.
