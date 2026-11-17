# RPI peer-review checklist

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Purpose:** distinguish implementation verification, real-model observations, and decision-grade evidence.

## E-007 real-agent evaluation

| Review item | Status | Evidence / note |
|---|---|---|
| Eval case keeps scorer/oracle data outside model-visible prompt | Pass | Declarative case and deterministic scorer code remain runner-side |
| Runner uses real model + live E-009 Gateway | Pass (implementation) | `eval_runner.py` invokes `local_agent.py`, Ollama, and the E-009 Gateway |
| Per-run identity, trace and usage retention | Pass (implementation) | Unique run IDs and raw JSONL in short-retention workflow artifacts; token counts come from Ollama responses |
| Candidate/proposal/validation/plan provenance | Pass (scorer implementation) | Three deterministic scorers check exact candidate contract, hash lifecycle, and behavioral safety |
| Failure taxonomy | Pass (implementation) | Separates provider HTTP, transport loss, agent/runner timeout, resource-budget exhaustion and explicit OOM evidence; nested schema/preservation/validation/repair diagnostics remain distinct |
| Aggregate token/time budget | Pass (mock) | Mock runner proves next repetition is not started when worst-case token/time reservation does not fit; resource stops are ineligible and distinct from agent failures |
| Local inference currency cost | Correctly unpriced | Ollama tariff is null; no fake $0 usage is emitted. Electricity, hardware depreciation and hosted-runner cost are not estimated |
| Deterministic Qwen3 cohort | **Fail — 0/3 accepted** | [Run 44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547), [artifact 14332334550](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547/artifacts/14332334550): all fail validate with AN021; array input was correct, but IR omitted `ir_version` and existing operations; model called plan after `result.valid=false` |
| Independence of deterministic repetitions | **Not established** | All temp 0 / seed42, matching token/tool path, Ollama prompt/KV reuse. Reproductions of one failure path, not independent model samples |
| Stochastic Qwen3 probe | **Fail — exploratory only** | [Run 44105440141](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141), [artifact 14337879630](https://github.com/mojtaba-arvin/agent-native/actions/runs/44105440141/artifacts/14337879630): temp 0.7/seed20261117 produced full top-level IR and array inputs, but changed five existing operation contracts; first proposal blocked by inspect-all gate; after all six inspections no second proposal before 900s wall timeout |
| Corrected preservation/repair implementation | Pass (deterministic tests) | E-009 Gateway now captures inspected service/types/operation objects and rejects same-revision proposals that rewrite the existing base with `IR_PRESERVATION_MISMATCH`; local adapter counts all proposal attempts, caps them at three and preserves final JSON before semantic verification |
| Latest deterministic runner suite | Pass | 51 tests in [workflow 44149051059](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149051059), including timeout vs HTTP/transport vs explicit OOM classification |
| Post-Gateway-preservation real-model trial | **Ineligible — input budget exhausted** | [Workflow 44144939813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813), [artifact 14357367813](https://github.com/mojtaba-arvin/agent-native/actions/runs/44144939813/artifacts/14357367813): 48,307/48,000 input tokens after 5/6 inspections; 1,020s/1,200s; no AN021, validation, plan, provider error or OOM. See [run analysis](../experiments/e007/results/2026-11-17-deterministic-postfix-budget-exhaustion.md). The artifact's original eligibility flag was wrong; the corrected runner excludes per-run budget exhaustion and is covered by 51 tests. |
| Expanded-budget deterministic follow-up | **Running — do not close** | [Workflow 44149712970](https://github.com/mojtaba-arvin/agent-native/actions/runs/44149712970): one Qwen3 run at temperature 0 / seed 42, 96,000 input tokens / 1,800s wall cap; inspect raw artifact before any acceptance decision |
| Current real-model acceptance | **Open / not passed** | No real-model artifact after Gateway-owned exact-preservation enforcement, bounded proposal-attempt fix, and final-candidate retention proves the complete successful proposal → validate → safe plan path |

## E-005 interface and E-009 kernel

| Review item | Status | Evidence / note |
|---|---|---|
| Complete IR proposal schema | Pass | E-005 schema requires `ir_version`, `service`, `types`, and `operations`; operation inputs are declaration arrays |
| AN021 fix guidance | Pass | Validation returns actionable full-snapshot guidance |
| Semantic plan gate | Pass | Local agent blocks plan without `result.valid=true` on the current proposal hash |
| Gateway base-preservation gate | Pass | Same-revision proposal must preserve inspected service, types and each original operation exactly and in order |
| Bounded proposal-attempt budget | Pass | Counts all proposal calls, including Gateway-rejected calls, and rejects attempt 4+ |
| Final candidate evidence preservation | Pass | Parsed final JSON is saved before trusted verification with private file permissions |
| Durable audit sink | Pass | SQLite allow/deny persistence, reopen, concurrent append, append-only triggers and fail-closed handler prevention |
| E-005 suite | Pass | 17 tests in [workflow 44102058544](https://github.com/mojtaba-arvin/agent-native/actions/runs/44102058544) |
| Latest E-009 suite | Pass | 80 tests in [workflow 44128413303](https://github.com/mojtaba-arvin/agent-native/actions/runs/44128413303) |

## E-002 runtime-decision evidence

| Review item | Status | Evidence / note |
|---|---|---|
| Pre-registered weights and screening gates | Pass | Registered before matrix runs; [first workflow 44087449181](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087449181) |
| Two comparable ten-run diagnostic cohorts | Pass (diagnostic) | [First run](../experiments/e002/results/2026-11-17-ten-run-diagnostic.md) and [second run 44124537511](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511): each four candidates × 10 × 5,000 requests, concurrency32, warm-up250, randomized order |
| Functional/p99/throughput/RSS/startup screens | Pass | All four candidates completed 10/10 functional repetitions and passed these measured screens in both cohorts |
| CPU screen | **Fail for all candidates** | Every candidate exceeded 0.5 CPU seconds/5,000 requests in both cohorts; threshold not changed after observation |
| CPU gate cause/threshold analysis | Pass — diagnostic analysis | The 0.5 s/5k value was preregistered but has no product-capacity origin; two 10-run cohorts both show all four candidates above it. The analysis preserves the gate and rules out post-hoc relaxation; see [CPU analysis](../experiments/e002/cpu-gate-analysis.md) |
| CPU threshold product provenance | **Open** | Pre-registered experiment screen, but no product SLO, vCPU capacity target or cost model justifies 0.5 s/5k; see [CPU analysis](../experiments/e002/cpu-gate-analysis.md) |
| Deployable payload size | Pass — one diagnostic measurement/candidate | [Second artifact 14347795200](https://github.com/mojtaba-arvin/agent-native/actions/runs/44124537511/artifacts/14347795200): Go 10,012,310 B; Rust 4,991,320 B; WASI+Wasmtime 71,947,386 B; BEAM+ERTS 74,856,626 B. Linux x86_64, uncompressed payload + resolved ELF dependencies; package models differ |
| Ecosystem/operability rubric | Not measured | Rubric exists; candidate scores and supporting evidence not completed |
| Comparable fault injection | Not measured | Deadline, overload, cancellation, worker crash/reclaim, retries, idempotent replay, outbox/inbox and tenant/data-integrity assertions are not yet run across all arms |
| Final weighted ranking/runtime selection | Not performed | Correctly deferred; provisional CPU eligibility screen was missed by all candidates and two dimensions remain unmeasured |

## Overall review decision

- [x] Research, plan, evidence index and design-decision log exist.
- [x] E-009 durable audit sink is integrated and passes CI.
- [x] E-005 full-IR schema and AN021 fix hint pass deterministic tests.
- [x] E-007 runner taxonomy and aggregate budget fail-fast pass deterministic tests.
- [x] E-009 Gateway enforces exact base preservation and blocks invalid plans.
- [x] Two E-002 ten-run diagnostics and one package-size measurement are published without selecting a runtime.
- [ ] Run one bounded real-model attempt after the latest Gateway preservation and candidate-retention changes; inspect the artifact before closing E-007.
- [ ] Derive or reaffirm CPU gate from a product capacity/cost model before a new pre-registered run.
- [ ] Complete comparable fault-injection and evidence-based ecosystem/operability scoring before any runtime decision.

**Cycle status:** partially validated. Deterministic implementation evidence is substantially stronger, but no real Qwen3 attempt has completed a valid proposal/validate/plan cycle. E-002 remains diagnostic, not decision-grade. Do not declare the RPI cycle complete or select a runtime.
