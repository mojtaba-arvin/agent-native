# M3 model feasibility: zero-cost CPU candidate pool

**As of:** 2026-11-19  
**Task:** M3-003  
**Status:** Provisional candidate pool with immutable model manifests pinned. No cohort model is selected or preregistered.

## Objective and non-goals

Identify model/runtime combinations that can execute the existing E009 AgentGateway loop on a free public GitHub Actions runner. This is a feasibility pilot, not the M3 hidden-oracle cohort.

The pilot must preserve the existing agent boundary:

`inspect → propose_delta → validate → plan`

It must never call `service.apply`, never access a hidden oracle, and never use a paid API or GPU. A successful E009 local verification is evidence only for this public feasibility task; it is not M3 acceptance.

## Free execution envelope

GitHub documents standard Linux hosted runners as 4 vCPU, 16 GB RAM, and 14 GB SSD. Standard hosted runner usage is free for public repositories, and each job receives a fresh runner instance. See [GitHub-hosted runner specifications and billing](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

The initial plan is CPU-only:

- Runner: `ubuntu-latest`, standard public-repository runner.
- Ollama runtime image: `ollama/ollama@sha256:a717bfc1c56acfc2e85d3109bd40a7646258ec9062c40cea83b9ed0927eb4223` (Linux amd64 manifest; version 0.40.15).
- Python client image: `python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
- Model download occurs before sandbox execution and uses only the public Ollama registry.
- During inference, the Ollama server has `--network none`; the Python agent shares only that isolated network namespace to reach Ollama over loopback. No external network is available.
- Agent and model server have separate cgroup limits. The agent has no apply capability and no access to hidden-oracle data.

The runtime image and model manifest digests are recorded in every run artifact. The bootstrap run produced the immutable manifest, config, model-layer, quantization, and model-size digests now committed in [model-lock.json](../experiments/e007/model-lock.json). The workflow compares every freshly pulled tag against this lock and fails closed on any mismatch. The candidate registry mirrors the key pins; the lock SHA-256 is also included in each run summary.

The lock records identity, not capability. The bootstrap run [44509769849](https://github.com/mojtaba-arvin/agent-native/actions/runs/44509769849) completed with all three models safely isolated but **0/3 completed the E009 agent loop**. The 350M model returned no tool call or final candidate; the 1B model passed the target operation name to `interface.describe`; the 3B model repeated service inspection and attempted to inspect the operation it was supposed to add. No apply was attempted, no hidden oracle was used, and no sandbox safety violations were recorded. These failures remain in the raw artifact (artifact ID `14521961180`, SHA-256 `d968fe09cc1b89d5ca6e68cbc0f314bcfdb92144940e1150f0873d4d31e54974`).

The 3B trace also exposed an inconsistency in the Gateway's `minimal` disclosure flow; the corrective change is tracked in PR #97. The candidate cohort remains unselected until a fresh locked run after that repair produces reproducible results.

## Provisional same-family model tiers

The first candidate family is IBM Granite 4.0 Hybrid, distributed through the [official Ollama library](https://ollama.com/ibm/granite4). The family advertises code-related and function-calling tasks and Apache 2.0 licensing. The `-h` variants use a hybrid Mamba2 architecture. To avoid quantization confounding, the initial tiers explicitly use Q4_K_M variants for all three model sizes; H-350M, H-1B, and H-Micro are all dense `granitehybrid` models.

| Tier | Provisional model tag | Parameters | Ollama page size | Purpose |
|---|---|---:|---|
| Weak | `ibm/granite4:350m-h-q4_K_M` | 340M | 223 MB | Lower-capability baseline |
| Medium | `ibm/granite4:1b-h-q4_K_M` | 1.46B | 901 MB | Small CPU model |
| Strong | `ibm/granite4:3b-h` | 3.19B | 1.9 GB | Larger dense hybrid candidate |

These are candidate labels, not a claim that the 3B model will pass. The bootstrap `/api/show` metadata reported parameter sizes of 340.33M, 1.5B, and 3.2B respectively; the model-card totals in the table remain 340M, 1.46B, and 3.19B. The explicit Q4_K_M tags avoid the Q8_0 defaults exposed by the unqualified H-350M and H-1B tags. Exact quantization, size, configuration digest, and manifest SHA-256 are read from the pulled manifests and retained per run. The model identity is now pinned in `model-lock.json`; model capability remains unqualified until the fresh feasibility gate passes.

Official model references:
- [IBM Granite 4.0 Ollama model family](https://ollama.com/ibm/granite4)
- [Granite 4.0 H-350M model card](https://huggingface.co/ibm-granite/granite-4.0-h-350m) and [Q4_K_M Ollama tag](https://ollama.com/ibm/granite4:350m-h-q4_K_M)
- [Granite 4.0 H-1B model card](https://huggingface.co/ibm-granite/granite-4.0-h-1b) and [Q4_K_M Ollama tag](https://ollama.com/ibm/granite4:1b-h-q4_K_M)
- [Granite 4.0 H-Micro 3B model card](https://huggingface.co/ibm-granite/granite-4.0-h-micro) and [Q4_K_M Ollama tag](https://ollama.com/ibm/granite4:3b-h)
- [Ollama tool-calling API](https://docs.ollama.com/capabilities/tool-calling)

### Challenger and exclusions

- **Granite 4.0 H-Tiny 7B-A1B** and **Granite 4.2 3B/8B** are possible challengers if the dense Granite 4.0 H tiers fail the task-quality gate. H-Tiny is a hybrid MoE architecture, so it is not part of the initial dense size-tier comparison. The Granite 4.2 30B variant is not a first-pass candidate for a 16 GB runner.
- **Qwen3.5** is not in the initial Ollama cohort. Ollama issue [#19694](https://github.com/ollama/ollama/issues/19694), opened in November 2026, reports tool-call argument corruption for code-like content. This is directly relevant to multiline source and patch arguments. Reconsider only after the issue is resolved or an alternate parser/runtime passes the same regression.
- **Gemma 4** is not in the initial llama.cpp cohort. llama.cpp issue [#25986](https://github.com/ggml-org/llama.cpp/issues/25986) documents a parser failure involving long multiline tool arguments. This issue is specific to the llama.cpp path and does not prove an Ollama failure; any future Gemma 4 candidate must pass runtime-specific regression tests first.
- Previous Qwen3 8B pilot evidence remains exploratory and is not reused as a passing tier.

## Feasibility protocol

The workflow uses the existing [E009 local agent](../experiments/e009/local_agent.py) and the public `AGENT_TASK_DELTA.md` task. It does not invent a new mock tool schema.

Fixed configuration across all three tiers:

- Task: add the read-only `get_item_by_normalized_name` operation.
- Proposal mode: `delta`.
- Disclosure: `minimal`.
- Tool-schema arms: `progressive` and `upfront`, executed separately for every model so schema-discovery overhead can be distinguished from model capability.
- Context: 16,384 tokens.
- Output budget: 2,048 tokens.
- Input budget: 12,000 tokens.
- Tool-call budget: 20.
- Wall-clock budget: 600 seconds per model.
- Sampling: temperature 0, top-p 1, seed 42.
- Apply: disabled.
- Retries: zero; failures and timeouts are retained.

The model server and agent client run in isolated containers. The model weights are mounted read-only during inference. The agent can reach only the local Ollama endpoint and its local AgentGateway subprocess. The smoke records:

- model tag, manifest SHA-256, config digest, quantization and model size;
- Ollama image digest and runtime version;
- input/output tokens, tool-call count, wall time and failure code;
- exact candidate hash, validation result, plan result and final local-verification status;
- sandbox attestation and a raw artifact bundle.

The model smoke wrapper treats a model failure as a data point, not an infrastructure failure. It fails the workflow only for safety/infrastructure violations such as external network access, an apply attempt, missing raw evidence, or a failed sandbox probe.

### Progressive-arm baseline

Two real progressive-arm runs are retained:

- Bootstrap [44509769849](https://github.com/mojtaba-arvin/agent-native/actions/runs/44509769849): 0/3 verified. The 350M tier made no tool call; the 1B tier supplied the target operation name to `interface.describe`; the 3B tier repeated service inspection and selected the new operation as if it already existed.
- Post-Gateway-repair [44511342601](https://github.com/mojtaba-arvin/agent-native/actions/runs/44511342601): still 0/3 verified. The 350M and 3B tiers returned no tool calls; the 1B tier repeated `interface.describe(name="service.inspect")` six times until the input-token budget was exceeded.

The second run confirmed that all three pulled model manifests still matched the bootstrap lock. Both runs recorded zero safety violations, no apply attempt, no hidden oracle, and zero paid API/GPU spend. Their raw artifacts are retained by the corresponding Actions runs. The next locked run executes both tool-schema arms for each model; the upfront arm will reveal whether progressive schema discovery, rather than the models' underlying tool-use ability, is the dominant failure source.

## Decision gates

A tier can enter the eventual M3 cohort only after:

1. its full model manifest digest and runtime image digest are pinned;
2. tool-call arguments survive the real Ollama parser, including multiline code-like content;
3. the E009 agent completes the exact-hash `propose_delta → validate → plan` flow without apply;
4. the same candidate passes the local deterministic verifier;
5. token, tool-call and wall-clock budgets are respected;
6. all failures remain visible and the result is reproducible on a fresh public runner.

This pilot does not create hidden-oracle data, does not freeze the M3 cohort, and does not satisfy M3-001 or M3-002. Protected `m3-evaluator` Environment rules and evaluator-only hidden-oracle custody remain separate gates.

## Cost and security

- Paid API ceiling: USD 0.
- GPU usage: prohibited.
- Permitted compute: public-repository GitHub Actions hosted CPU runners only.
- No provider credentials or GitHub secrets are passed to the agent.
- No external network during model inference.
- No apply, deployment, hidden oracle, or production data.


## Locked post-compaction feasibility run — 2026-11-19

**Run:** [44529848174](https://github.com/mojtaba-arvin/agent-native/actions/runs/44529848174)  
**Source revision:** `61e29b03e60b5a6feaf53fa7b309eb4a82af63b3`  
**Artifact:** `14533985747`, SHA-256 `d6db65fb69faf7ce2ac35ae0ce484c833e7a59a954cfadda9cd18bf7513c73d6`  
**Model-lock SHA-256:** `8dd6e4e2acbea225dbd4fa2b4428f3691f11176be862539430aee0aced67bc17`

The locked run completed all six cells (three model tiers × progressive/upfront disclosure), with **0/6 full inspect → propose → validate → plan completions**:

| Tier | Progressive | Upfront |
|---|---|---|
| Weak, 350M | `provider_final_content_missing`, 0 tool calls | `provider_final_content_missing`, 0 tool calls |
| Medium, 1B | `repeated_invalid_tool_call`, 4 tool calls | `provider_final_content_missing`, 1 tool call |
| Strong, 3B | `provider_final_content_missing`, 0 tool calls | `input_token_budget_exceeded`, 4 tool calls |

The medium progressive trace retained the exact `service.inspect` input schema after compaction, but the model repeated `interface.describe` for the same tool and then attempted to describe the not-yet-exposed target operation. The strong upfront trace inspected the service, submitted one Gateway-accepted proposal, then repeated the same proposal. The Gateway rejected the duplicate with `PROPOSAL_REQUIRES_VALIDATION` and explicitly instructed the model to validate the existing `change_set_id`; the model did not complete validation or planning. The strong upfront run consumed 12,702 cumulative input tokens against the fixed 12,000-token limit. The weak tier and strong progressive tier returned no tool calls and no final candidate.

### Harness finding: schema state is not provider-native tool availability

Raw provider telemetry records `tool_definition_count=1` on every request. The provider receives only the generic `agent.invoke` function schema; discovered Gateway schemas are preserved in the conversational state ledger but are not exposed as individual native function definitions. Thus PR #100 fixed schema loss during compaction, but did not make those schemas part of the provider's structured tool contract. This is a separate harness limitation tracked as M3-004.

The workflow completed its evidence and safety gates: the agent and Ollama containers remained non-root, no-network during inference, resource-limited, and no-apply. The artifact reports zero safety violations, zero paid API spend, no GPU, and no hidden-oracle use. The workflow's successful conclusion means the bounded feasibility protocol ran and retained its evidence; it does **not** mean any model passed.

Post-merge repository CI [44529847920](https://github.com/mojtaba-arvin/agent-native/actions/runs/44529847920) passed Layer 0 and Layer 1 on the same source revision. No model is selected or frozen for the M3 cohort. M3-003 is complete as a bounded feasibility evaluation with a negative qualification result; M3-001 and M3-002 remain blocked/pending until a qualifying model path and protected evaluator-only oracle custody are both demonstrated.
