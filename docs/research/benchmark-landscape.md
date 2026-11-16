# Backend Agent Benchmark Landscape

Research snapshot: 2026-11-16

This document records external evaluation work relevant to Agent Native. It is not a leaderboard and does not imply that the project has reproduced any published result.

## 1. ABC-Bench

**Source:** Yang et al., *ABC-Bench: Benchmarking Agentic Backend Coding in Real-World Development*, Findings of ACL 2026.

- Official paper: https://aclanthology.org/2026.findings-acl.1142/
- PDF: https://aclanthology.org/2026.findings-acl.1142.pdf
- Dataset and harness: https://github.com/OpenMOSS/ABC-Bench
- Preprint: https://arxiv.org/abs/2601.11077

The paper describes 224 practical tasks collected from 127 MIT-licensed repositories, spanning 8 languages and 19 frameworks. The evaluation covers repository exploration, code editing, environment setup, containerized deployment, and external end-to-end API tests. The repository reports that 92 tasks require autonomous environment configuration and containerized service startup.

**Implication:** Agent Native must not use code generation or unit-test success as its sole success criterion. Environment setup, deployment, and external behavior are first-class evaluation stages.

**Limitations to account for:** benchmark tasks are drawn from existing repositories and reflect their task construction and test oracles. A framework could overfit to benchmark conventions. Agent Native therefore needs its own held-out tasks and a transparent protocol in addition to external benchmark runs.

## 2. BackendForge

**Source:** Guo et al., *BackendForge: Benchmarking Agentic End-to-End Code Generation with Backend Services*, Findings of EMNLP 2026.

- Official paper: https://aclanthology.org/2026.findings-emnlp.2236/

The paper describes 56 contract-defined backend generation tasks derived from real open-source applications. Agents receive a visible specification and OpenAPI contract, must produce a Dockerized service, and are evaluated through HTTP tests. The published abstract reports a substantial gap between results under a base oracle and a more demanding final oracle: the best reported model succeeds on 55.4% under the base oracle and 28.6% under the final oracle.

**Implication:** API contract compliance alone can hide missing behavior. Our evaluator should validate the specification against the oracle and include meaningful edge cases, authorization, state transitions, and operational behavior. Test-oracle quality must itself be reviewed.

## 3. GitTaskBench

**Source:** Ni et al., *GitTaskBench: A Benchmark for Code Agents Solving Real-World Tasks Through Code Repository Leveraging*.

- Paper: https://arxiv.org/abs/2508.18993
- AAAI publication: https://ojs.aaai.org/index.php/AAAI/article/download/40533/44494

The work emphasizes realistic repository tasks and economic value, combining task success with token cost and human labor value. Its reported results show that complex repository-centric tasks remain difficult and that environment setup and dependency resolution account for many failures.

**Implication:** record setup failures separately, but do not exclude them from the overall end-to-end delivery score. Measure total cost per accepted task rather than tokens in isolation.

## 4. SWE-PolyBench

**Source:** Rashid et al., *SWE-PolyBench: A multi-language benchmark for repository level evaluation of coding agents*.

- Paper: https://arxiv.org/abs/2504.08703

The benchmark contains repository-level tasks across multiple languages and includes bug fixes, feature additions, and refactoring.

**Implication:** use multi-language evaluation to test whether Agent Native's claimed agent-first design transfers across ecosystems. A single-language prototype cannot substantiate language independence.

## 5. Design consequences for Agent Native

1. Evaluate the full lifecycle from repository discovery to deployed behavior.
2. Keep acceptance oracles independent from the agent's own generated tests.
3. Include environment configuration, dependency installation, and service startup in the task.
4. Measure task success, regression, security, runtime, human intervention, wall-clock time, and total cost.
5. Run multiple trials and report distributions for stochastic agents.
6. Maintain held-out tasks to reduce benchmark overfitting.
7. Compare against established frameworks under matched conditions.
8. Publish task definitions, environment versions, evaluator versions, and failure classifications.
9. Distinguish framework failure, agent failure, evaluator failure, and infrastructure failure.
10. Treat published benchmark numbers as external evidence, not as results reproduced by this project.

## 6. Open questions

- Which ABC-Bench task subset can be run reproducibly within the project's available compute budget?
- Does BackendForge release an executable harness and dataset compatible with our environment?
- Which benchmark tasks can be legally redistributed, and which require linking to upstream datasets?
- How should we score partially completed tasks without obscuring safety-critical failures?
- How can benchmark tasks measure maintainability and safe evolution rather than only initial API behavior?
