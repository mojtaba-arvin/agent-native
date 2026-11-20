# T10 — T09 runtime decision

**Decision date:** 20 November 2026  
Task: T10 (#114)  
Decision: **NO SELECTION**  
**Selected runtime:** None. This is an evidence-based deferral under T02, not a selection of a "none" runtime and not a rejection of any candidate architecture.

## 1. Rule applied

The decision rule is scoped to the authenticated Agent/tool-execution control-plane workload defined in T02.

This record applies the existing [T02 SLO and Rust-versus-Go decision rule](T02_SLO_AND_RUNTIME.md) without changing its workload, thresholds, gates, weights, or candidate boundary.

T02's formal runtime comparison is **Rust/Tokio + Hyper versus Go/net/http**. Its decision-grade workload is the authenticated Agent/tool-execution control plane. WASI Preview 2/Wasmtime and Elixir/BEAM appear in T09's exploratory matrix, but they are not members of T02's formal Rust-versus-Go decision pair.

The T02 rule does not permit a winner when required evidence is incomplete. A candidate is eligible only after the shared product contract, security/integrity and failure-semantics gates, request-path performance gates, and comparable measurement conditions are demonstrated. If required evidence is absent, it is **not measured**, not zero and not a pass. A weighted score is not calculated from an incomplete cohort.

## 2. T09 evidence examined

The source evidence is documented in the [T09 controlled-cgroup evidence record](../experiments/e002/T09-evidence.md); the machine-readable decision is D-0016 in the root [DECISIONS.json](../DECISIONS.json).

- **Source revision:** `acfd8d0f775d46b4f0dea39ade423e445efc8fd5`
- **Workflow:** [Agent Native CI run 44741277036](https://github.com/mojtaba-arvin/agent-native/actions/runs/44741277036)
- **Retained raw artifact:** [e002-controlled-cgroup-matrix-44741277036 (artifact 14630464028)](https://github.com/mojtaba-arvin/agent-native/actions/runs/44741277036/artifacts/14630464028)
- **Run set:** four candidates × ten randomized repetitions = 40 runs; 5,000 measured requests per repetition (200,000 total), concurrency 32, and 250 warm-up requests per repetition.
- **Endpoint and success contract:** the in-memory `GET /work?ms=0` probe; HTTP 200 with exact body `completed:0`.
- **Load model:** closed-loop request generation, HTTP/1.1 keep-alive disabled (one connection per request), using a compiled Go `net/http` load generator.
- **Resource boundary:** each candidate ran separately in a cgroup-v2 container with one CPU (`cpu.max = 100000 100000`), candidate pinned to CPU 0, and a **2 GiB** memory ceiling. The load generator ran outside the candidate cgroup on CPU 1. Candidate CPU was measured from cgroup `cpu.stat` usage deltas.
- **Host:** ephemeral GitHub-hosted Ubuntu 26.04.1 x86_64 VM, Linux 7.0.0-1019-azure, AMD EPYC 9V45. The run does not establish exclusive physical-host tenancy or remove hypervisor/neighbor noise.
- **Toolchains:** Go 1.23.12; Rust 1.100.0 / Cargo 1.100.0; Wasmtime 50.0.1; Erlang/OTP 29 and Elixir 1.20.5.

All 40 repetitions passed the narrow HTTP functional check and the raw request-level traces were retained. This establishes reproducibility for this diagnostic probe; it does not establish product-contract conformance.

## 3. Observed trade-offs

Values below are the T09 artifact's per-candidate mean ± sample standard deviation; peak cgroup memory is the median. They are descriptive results for the stated probe only.

| Candidate | Throughput mean ± SD (req/s) | p99 mean ± SD (ms) | CPU mean ± SD (s / 5,000) | Peak cgroup memory median (MiB) | Functional runs |
|---|---:|---:|---:|---:|---:|
| Go/net-http | 10,514.85 ± 367.04 | 4.575 ± 0.330 | 0.2935 ± 0.0095 | 7.24 | 10/10 |
| Rust/Tokio + Hyper | 10,371.60 ± 376.13 | 4.609 ± 0.197 | 0.2628 ± 0.0054 | 4.15 | 10/10 |
| WASI P2 / Wasmtime | 6,428.70 ± 115.64 | 7.672 ± 0.260 | 0.7744 ± 0.0122 | 21.50 | 10/10 |
| Elixir/BEAM | 9,795.92 ± 429.49 | 5.014 ± 0.237 | 0.4874 ± 0.0165 | 46.83 | 10/10 |

The run-level medians for the two T02 candidates, shown only as diagnostic context, are:

| Candidate | Median throughput (req/s) | Median p99 (ms) | Median CPU (s / 5,000) | Median peak memory (MiB) | Median startup (ms) |
|---|---:|---:|---:|---:|---:|
| Go/net-http | 10,630.32 | 4.6172 | 0.2896 | 7.24 | 15.02 |
| Rust/Tokio + Hyper | 10,384.34 | 4.6634 | 0.2612 | 4.15 | 14.82 |

### Trade-off interpretation

- **Go/net-http** had the highest mean and median throughput in this probe and a marginally lower p99 than Rust. Its measured CPU use and peak cgroup memory were higher than Rust's in the same probe.
- **Rust/Tokio + Hyper** used less measured CPU and memory than Go in this probe, while its throughput was slightly lower and its p99 was close to Go's. This does not establish a product-workload advantage.
- **WASI P2/Wasmtime** and **Elixir/BEAM** completed all ten diagnostic repetitions, with lower throughput and higher CPU/memory than the Rust/Go probes in this specific workload. T02 does not rank them in its Rust-versus-Go selection rule; their different runtime/host boundaries remain exploratory factors.

These measurements are not normalized into a T02 score. A small numerical lead on a deliberately trivial endpoint is not evidence of a corresponding product-level trade-off.

## 4. T02 eligibility assessment

The registered T02 product envelope requires **one vCPU and one GiB** of service memory, with a rate-controlled open-loop arrival model. T09 used one vCPU but allowed 2 GiB of service memory and used closed-loop generation; it therefore does not test the complete registered envelope.

| T02 requirement | T09 evidence | Assessment for T02 |
|---|---|---|
| Authenticated Agent/tool-execution control-plane request mix | In-memory `GET /work?ms=0` only | **Not measured** |
| Authentication, trusted tenant resolution, contract validation and default-deny authorization | Not exercised by this endpoint | **Not measured** |
| Durable audit before response; PostgreSQL/storage and atomic job/outbox/idempotency admission | No database, durable audit, outbox or idempotency path in this probe | **Not measured** |
| Registered 60/20/10/10 product request mix, including expected denials | Not present | **Not measured** |
| Rate-controlled open-loop 100 completed req/s | Closed-loop concurrency 32; it does not establish offered-load behavior at 100 req/s | **Not measured** |
| One-vCPU / one-GiB product envelope | One vCPU was enforced; the memory ceiling was 2 GiB, not 1 GiB | **Incomplete** |
| Product black-box, security/integrity and complete failure-semantics hard gates | The 40/40 result covers only the endpoint's HTTP status/body contract | **Not measured** |
| Controlled-host capacity claim | GitHub-hosted VM; cgroup isolation is recorded, but exclusive physical-host isolation is not established | **Not decision-grade** |
| Complete comparable T02 score inputs and analysis | T09 does not supply product-workload ecosystem/operability and fault-semantics evidence, a comparable complete product artifact measure, or the registered score/paired-bootstrap/weight-sensitivity analysis | **Incomplete** |

The fact that the probe's throughput is numerically above 100 req/s, its p99 is below 100 ms, and its CPU/memory use is small **does not count as passing T02's product gates**. The workload, arrival model, memory ceiling, and host evidence are not the registered product measurement boundary. T09's 10/10 probe successes cannot be substituted for the product positive/negative/fault-injection suite.

## 5. Decision and alternatives

**Outcome: no runtime selected. No weighted score is calculated.** T02's incomplete-evidence branch applies: the product workload and multiple hard-gate dimensions are not measured. No candidate has demonstrated eligibility for selection from this cohort.

The following selection shortcuts are rejected:

1. **Select Go because it leads the probe on throughput.** Rejected: this lead is measured only on the closed-loop in-memory endpoint and says nothing about authenticated requests, durable storage, or the registered open-loop product workload.
2. **Select Rust because it uses less probe CPU and memory.** Rejected for the same evidence-boundary reason. Those results are useful trade-off observations, not product eligibility evidence.
3. **Promote WASI or BEAM as the T02 winner.** Rejected as an application of this rule: T02 formally compares Rust and Go, while WASI and BEAM are exploratory candidates outside that pair.
4. **Eliminate any candidate architecture from these results.** Rejected: T09 does not test the product contract or the required hard gates. Rust, Go, WASI and BEAM remain research candidates; none is rejected as an architecture by this decision.

## 6. Evidence required to reopen selection

A future decision-grade comparison must implement the same authenticated control-plane behavior and durable storage contract for both T02 candidates; pass all shared conformance, security/integrity and registered failure-semantics assertions; use the registered 60/20/10/10 request mix with open-loop arrivals at 100 completed requests/second; enforce one vCPU and one GiB per candidate; and run ten randomized 5,000-request repetitions at concurrency 32 on the required controlled host.

It must retain request-level traces and per-run summaries, measure the registered latency, throughput, CPU, memory, throttling, storage/audit and idempotency outcomes, and complete the comparable startup, deployable-artifact, ecosystem/operability and failure-semantics inputs. Only then may the T02 weighted score, 10,000-resample paired 95% bootstrap interval, and ±20% weight-sensitivity analysis be evaluated.

Until that evidence exists, the product runtime remains **unselected**. The T09 raw artifact remains diagnostic evidence and is not discarded or rescored as a product benchmark.


## 7. Decision integrity

The aggregate `matrix.json` explicitly records `decision_grade: false`. The runner is a **shared GitHub-hosted** environment, not an exclusive physical host. The four candidates are **not rejected as architectures** by this decision; they remain research candidates pending comparable product evidence.
