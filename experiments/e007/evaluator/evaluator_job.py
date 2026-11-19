"""Synthetic-oracle evaluator used only by the M3 topology smoke.

The evaluator reads candidate JSON as data; it never imports or executes agent
output. The synthetic oracle is created inside this evaluator process in a
private temporary directory. It is not a hidden benchmark oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from agent_stub import SMOKE_PAYLOAD, canonical_json
from boundary import EvaluatorBoundaryError, validate_candidate_continuity, verify_evaluator_boundary


def _write_synthetic_oracle(directory: Path) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        directory.chmod(0o700)
    oracle_path = directory / "oracle.json"
    oracle_path.write_text(json.dumps({"expected_candidate": SMOKE_PAYLOAD}, sort_keys=True) + "\n", encoding="utf-8")
    if os.name == "posix":
        oracle_path.chmod(0o600)
    return oracle_path


def evaluate_candidate(workspace: str | Path, candidate_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve(strict=True)
    candidate_input = Path(candidate_path)
    candidate_for_size = candidate_input if candidate_input.is_absolute() else workspace_path / candidate_input
    if candidate_for_size.stat().st_size > 64 * 1024:
        raise EvaluatorBoundaryError("candidate artifact exceeds the 64 KiB limit")

    with tempfile.TemporaryDirectory(prefix="m3-evaluator-private-", dir="/tmp") as private_root:
        oracle_path = _write_synthetic_oracle(Path(private_root))
        evidence = verify_evaluator_boundary(workspace_path, candidate_input, oracle_path)

        candidate = json.loads(evidence.candidate_path.read_text(encoding="utf-8"))
        semantic_hash = validate_candidate_continuity(candidate)
        actual_hash = hashlib.sha256(canonical_json(candidate.get("candidate"))).hexdigest()
        if semantic_hash != actual_hash:
            raise EvaluatorBoundaryError("candidate payload does not match its phase hash")

        oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
        if candidate.get("candidate") != oracle.get("expected_candidate"):
            raise EvaluatorBoundaryError("candidate does not match the synthetic topology-smoke oracle")

        summary = {
            "schema_version": "m3-topology-score-v1",
            "mode": "synthetic_topology_smoke",
            "passed": True,
            "candidate_artifact_sha256": evidence.candidate_sha256,
            "semantic_candidate_sha256": semantic_hash,
            "no_apply": True,
            "oracle_external_to_workspace": True,
            "oracle_path_disclosed": False,
            "oracle_contents_disclosed": False,
        }

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if os.name == "posix":
        output_file.chmod(0o600)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score an M3 topology-smoke candidate in the evaluator job")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    evaluate_candidate(args.workspace, args.candidate, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
