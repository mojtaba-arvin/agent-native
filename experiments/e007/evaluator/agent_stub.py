"""Deterministic agent stub used only by the M3 topology smoke.

This is not an LLM agent and does not exercise M3 acceptance. It proves that
the agent job can emit a narrowly allowlisted candidate/trace artifact without
receiving or knowing anything about evaluator oracle data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

SMOKE_PAYLOAD: dict[str, Any] = {
    "operation": "inventory.topology_smoke",
    "resource": "/inventory/items/smoke",
    "value": {"quantity": 1},
}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def build_candidate() -> dict[str, Any]:
    digest = hashlib.sha256(canonical_json(SMOKE_PAYLOAD)).hexdigest()
    return {
        "schema_version": "m3-candidate-v1",
        "task_id": "topology-smoke",
        "no_apply": True,
        "apply_invoked": False,
        "candidate": SMOKE_PAYLOAD,
        "phases": {
            phase: {"candidate_sha256": digest}
            for phase in ("proposal", "validation", "plan")
        },
    }


def write_candidate(output_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    candidate = build_candidate()
    candidate_path = directory / "candidate.json"
    trace_path = directory / "trace.jsonl"
    candidate_path.write_text(json.dumps(candidate, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    digest = candidate["phases"]["proposal"]["candidate_sha256"]
    trace_path.write_text(
        json.dumps(
            {"event": "candidate_created", "mode": "deterministic_topology_smoke",
             "candidate_sha256": digest, "apply_invoked": False},
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    if os.name == "posix":
        candidate_path.chmod(0o600)
        trace_path.chmod(0o600)
    return candidate_path, trace_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the deterministic M3 agent topology-smoke artifact")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    write_candidate(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
