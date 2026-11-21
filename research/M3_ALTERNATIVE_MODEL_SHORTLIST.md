# Alternative CPU tool-calling model shortlist

**Research date:** 2026-11-19  
**Purpose:** identify a separate candidate pool if the active Granite 4.0 feasibility rerun (M3-005) still fails. This is a shortlist only, not a qualification result or cohort dispatch.

## Candidate tiers

| Nominal tier | Exact Ollama tag | Published download size | Published context | Evidence |
|---|---|---:|---:|---|
| Weak | `qwen3:1.7b` | 1.4 GB | 40K | Qwen3 library lists the `tools` capability and the 1.7B tag |
| Medium | `granite4.2:3b` | 2.2 GB | 128K | Granite 4.2 lists tool usage and function-calling tasks; Apache 2.0 |
| Strong | `qwen3:4b` | 2.5 GB | 256K | Qwen3 library lists the `tools` capability and the 4B tag |

These tier labels are **nominal size tiers only**. They do not assert that Qwen3 4B is more capable than Granite 4.2 3B on the E-009 task. All three are small enough to justify an initial CPU feasibility attempt under the existing 10 GiB model-server memory ceiling, but published download size is not peak runtime memory. Actual memory, latency, and tool behavior must be measured in the pinned no-network runner.

## Reserve candidate

| Tag | Published download size | Context | Why reserve only |
|---|---:|---:|---|
| `gemma4:e2b` | 4.6–7.5 GB | 128K | Official Ollama library describes agentic workflows and tool support, but the published weight range leaves less headroom under the 10 GiB server limit |

Gemma 4 E2B is not in the primary three-tier shortlist. Include it only if measured runtime memory leaves sufficient headroom for the pinned server and context configuration.

## Evidence sources

1. [Ollama Qwen3 library](https://ollama.com/library/qwen3) — tool capability; tags and published sizes for 1.7B and 4B variants.
2. [Ollama Granite 4.2 library](https://ollama.com/library/granite4.2) — tool usage, function-calling tasks, Apache 2.0, and the 3B tag/size.
3. [Ollama Gemma 4 library](https://ollama.com/library/gemma4) — agentic workflow/tool capability and E2B size range.
4. [Ollama Gemma 4 E2B details](https://ollama.com/library/gemma4:e2b) — effective parameter count and context metadata.

## Execution boundary

- M3-005 remains the active, unchanged six-cell Granite 4.0 rerun. This shortlist does not modify its candidate manifest, model lock, runtime digest, token budget, or raw evidence.
- If M3-005 yields no qualified model, M3-007 must create a **separate** versioned candidate manifest and model lock, record exact immutable digests, preregister the new cohort, and verify the lock in a second no-network run before execution.
- A model's Ollama `tools` capability or a vendor's function-calling claim is not evidence of successful multi-step agent behavior. Qualification still requires inspect → propose → semantic validation → plan, exact candidate-hash continuity, and local verification.
- No paid API, GPU, hidden-oracle access, or apply is authorized for this shortlist.
