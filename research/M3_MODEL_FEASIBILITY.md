# M3 model feasibility: zero-cost CPU candidate pool

**As of:** 2026-11-19  
**Task:** M3-003  
**Status:** Provisional candidate pool only. No cohort model is selected or preregistered.

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

The runtime image and model manifest digests are recorded in every run artifact. Model tags are mutable; the first smoke is a bootstrap to obtain the full manifest digests. The cohort remains blocked until those digests are committed to a lock file and verified on a fresh run.

## Provisional same-family model tiers

The first candidate family is IBM Granite 4.0 Hybrid, distributed through the [official Ollama library](https://ollama.com/ibm/granite4). The family advertises code-related and function-calling tasks and Apache 2.0 licensing. The `-h` variants use a hybrid Mamba2 architecture. To avoid quantization confounding, the initial tiers explicitly use Q4_K_M variants for all three model sizes; H-350M, H-1B, and H-Micro are all dense `granitehybrid` models.

| Tier | Provisional model tag | Parameters | Ollama page size | Purpose |
|---|---|---:|---|
| Weak | `ibm/granite4:350m-h-q4_K_M` | 340M | 223 MB | Lower-capability baseline |
| Medium | `ibm/granite4:1b-h-q4_K_M` | 1.46B | 901 MB | Small CPU model |
| Strong | `ibm/granite4:3b-h` | 3.19B | 1.9 GB | Larger dense hybrid candidate |

These are candidate labels, not a claim that the 3B model will pass. The per-tag Ollama details report 340M, 1.46B, and 3.19B parameters respectively. The explicit Q4_K_M tags avoid the Q8_0 defaults exposed by the unqualified H-350M and H-1B tags. Exact quantization, size, configuration digest, and manifest SHA-256 are read from the pulled manifests and retained per run. No model is considered pinned until those values are verified and committed.

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
- Tool-schema arm: `progressive`.
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
