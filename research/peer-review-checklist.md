# RPI peer-review checklist

**Snapshot:** 17 November 2026  
**Branch:** `research/reboot-core`  
**Purpose:** internal review of the first RPI implementation cycle. This checklist distinguishes code/test evidence from real-model acceptance.

## E-007 real-agent evaluation

| Review item | Status | Evidence / note |
|---|---|---|
| Eval case and model-visible task do not expose scorer implementation or hidden oracle identifiers | Pass | The model receives the task through the E-009 task prompt and Agent Gateway; the case/scorer JSON is read only by the trusted runner |
| Runner invokes a real local model and live Agent Gateway | Pass (implementation) | `eval_runner.py` invokes `local_agent.py`, which calls Ollama and the E-009 gateway; 36 E-007 deterministic tests pass |
| Every repetition receives a distinct run identity and output directory | Pass (implementation) | The runner creates a unique eval directory and delegates unique run IDs to the E-009 runner |
| Candidate, proposal, validation, and plan hashes are correlated | Pass (implementation) | Deterministic scorer compares the candidate hash to the successful proposal, validation, and plan trace entries |
| Scorers and thresholds are deterministic and explicit | Pass | Three binary scorers; each threshold is 1.0; no LLM judge is used |
| Token usage comes from provider telemetry; missing usage is not treated as zero-cost | Pass (implementation) | Provider response records are checked; missing usage excludes a run from acceptance eligibility |
| Infrastructure failures and agent failures remain distinct | Pass after correction | Initial workflow omitted `OLLAMA_GO_TEMPLATE=false`; empty provider responses were initially counted as eligible. Root cause was identified, the classifier was fixed, and the workflow now uses the established Qwen3-compatible startup |
| Apply remains disabled and the scorer rejects any apply attempt | Pass | E-009 apply is disabled; behavioral-safety scorer requires no `service.apply` trace |
| Real-model acceptance | Pending | Corrected three-repetition Qwen3 run [44087982547](https://github.com/mojtaba-arvin/agent-native/actions/runs/44087982547) is still running at this snapshot; no pass claim is made |

## E-009 durable audit sink

| Review item | Status | Evidence / note |
|---|---|---|
| Allow and deny decisions are committed before the application handler/response | Pass | Integration test checks audit visibility from inside the handler and verifies denied decisions |
| Audit records survive database reopen | Pass | Test opens a second sink instance against the same file-backed SQLite database |
| Audit-store failure prevents handler execution | Pass | Integration test expects fail-closed 503 and verifies handler was not invoked |
| Concurrent appends are complete | Pass | Concurrent writer test verifies 24 unique records |
| Update/delete operations are rejected | Pass | SQLite triggers reject application-level update/delete attempts |
| Secret/body fields are excluded from the event contract | Pass | Strict field allowlist rejects unexpected event keys; tests inspect persisted event fields |
| Tamper-proofing and remote retention | Not implemented | SQLite triggers are defense-in-depth only; no remote replication, external ACL, cryptographic hash chain, or retention service |
| E-009 test suite | Pass | 72 tests pass in the latest verified E-009 CI run |

## E-002 decision matrix

| Review item | Status | Evidence / note |
|---|---|---|
| Weights and provisional gates fixed before the ten-run matrix | Pass | `experiments/e002/decision-matrix.md` committed before the `[benchmark]` dispatch |
| All candidates use the same request mix and run protocol | Pass | 10 repetitions × 5,000 requests, concurrency 32, warm-up 250, randomized candidate order |
| Raw repetitions and distributions retained | Pass | 40 run summaries and request-level JSONL in the 14-day workflow artifact |
| Mean, sample standard deviation, and bootstrap interval are reported | Pass | Result report contains distributions for throughput, p99, CPU, RSS, and startup |
| Hard-gate failures cannot be averaged away | Pass | Every candidate fails the pre-registered CPU gate; none receives a final weighted score |
| Runtime selection | Not performed | Correctly deferred; hosted-runner workload is diagnostic and incomplete |

## Overall review decision

- [x] Research and plan documents exist and define bounded acceptance criteria.
- [x] Durable local audit persistence is implemented and passes its integration tests.
- [x] E-002 ten-run diagnostic matrix is complete and documented without selecting a runtime.
- [ ] E-007 corrected real-model run has completed with three eligible repetitions and an inspected scorer report.
- [ ] `REPORT.md`, `EVALUATION.md`, and the resource policy have been updated with the corrected E-007 run outcome.

**Cycle status:** partially validated. The code-level eval loop, durable audit component, and E-002 data collection are implemented. Do not declare the RPI cycle complete until the corrected Qwen3 run is inspected and the final evidence report is reconciled with its raw artifacts.
