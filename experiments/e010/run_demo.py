"""Run the real-agent E-010 isolated sandbox apply demonstration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "e009"))
from local_agent import run

TASK_ID = "e010-sandbox-apply-lifecycle"
TASK_PATH = Path(__file__).with_name("AGENT_TASK.md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--arm", choices=("progressive", "upfront"), default="upfront")
    parser.add_argument("--results-dir", type=Path, default=Path("/tmp/agent-native-e010-runs"))
    parser.add_argument("--max-input-tokens", type=int, default=120000)
    parser.add_argument("--max-output-tokens", type=int, default=6000)
    parser.add_argument("--max-tool-calls", type=int, default=20)
    parser.add_argument("--max-wall-seconds", type=float, default=3000)
    parser.add_argument("--num-ctx", type=int, default=16384)
    parser.add_argument("--num-predict", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--think", action="store_true")
    args = parser.parse_args()
    for name in ("max_input_tokens", "max_output_tokens", "max_tool_calls", "max_wall_seconds", "num_ctx", "num_predict"):
        value = getattr(args, name)
        if isinstance(value, bool) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.num_predict > args.max_output_tokens or args.num_ctx < 1024:
        parser.error("invalid context or output budget")
    if not 0 <= args.temperature <= 2 or not 0 < args.top_p <= 1 or not 0 <= args.seed <= 2**32 - 1:
        parser.error("generation settings or seed out of range")
    run_args = SimpleNamespace(
        **vars(args),
        task_id=TASK_ID,
        task_path=TASK_PATH,
        allow_sandbox_apply=True,
    )
    record = run(run_args)
    print(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2))
    if record["status"] != "candidate_verified_locally":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
