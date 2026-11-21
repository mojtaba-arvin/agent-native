#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
from pathlib import Path
import sys

path = Path("docs/T02_SLO_AND_RUNTIME.md")
if not path.is_file():
    print("T02 acceptance: missing docs/T02_SLO_AND_RUNTIME.md")
    sys.exit(1)

text = path.read_text(encoding="utf-8")
required = {
    "decision record title": "# T02 — v0.1 SLO and Rust-versus-Go decision rule",
    "agent control-plane workload": "authenticated Agent/tool-execution control plane",
    "one-vCPU envelope": "1 vCPU",
    "memory envelope": "1 GiB",
    "sustained throughput": "100 completed requests/second",
    "concurrency": "concurrency 32",
    "tail-latency SLO": "p99 ≤ 100 ms",
    "CPU headroom": "sustained CPU ≤ 50% of one vCPU",
    "derived CPU budget": "25 CPU-seconds per 5,000 completed requests",
    "open-loop measurement": "open-loop",
    "request mix": "60% authorized read",
    "ten repetitions": "10 randomized repetitions per candidate",
    "controlled-host requirement": "controlled one-vCPU host",
    "cgroup accounting": "cgroup v2",
    "historical CPU threshold retired prospectively": "0.5 CPU-seconds per 5,000",
    "hard correctness gate": "zero authorization",
    "expected denial accounting": "expected 4xx denials",
    "Rust candidate": "Rust/Tokio + Hyper",
    "Go candidate": "Go/net/http",
    "weighted decision rule": "weighted score",
    "minimum selection margin": "5 points",
    "confidence interval requirement": "95% bootstrap confidence interval",
    "no automatic runtime selection": "no runtime selected",
}
missing = [name for name, marker in required.items() if marker not in text]
if missing:
    print("T02 acceptance: missing preregistered SLO/decision requirements:")
    for name in missing:
        print(f"- {name}")
    sys.exit(1)

print("T02 acceptance: SLO envelope, hard gates, measurement protocol, and Rust/Go decision rule are present.")
PY
