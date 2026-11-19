"""Preflight checks for a separately-run, oracle-isolated evaluator.

This module deliberately does not load or score oracle contents. It verifies
that an evaluator invocation receives an agent-visible candidate artifact and
an owner-provisioned oracle file outside the candidate workspace. These checks
are defense-in-depth preflight checks, not an OS/container isolation boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EvaluatorBoundaryError(ValueError):
    """The evaluator inputs violate the required trust boundary."""


@dataclass(frozen=True)
class BoundaryEvidence:
    candidate_path: Path
    oracle_path: Path
    candidate_sha256: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "candidate_sha256": self.candidate_sha256,
            "oracle_external_to_workspace": True,
            "oracle_path_disclosed": False,
        }


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _resolve_without_symlinks(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise EvaluatorBoundaryError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise EvaluatorBoundaryError(f"{label} does not exist") from error
    if Path(os.path.abspath(path)) != resolved:
        raise EvaluatorBoundaryError(f"{label} path traverses a symlink")
    if not resolved.is_file():
        raise EvaluatorBoundaryError(f"{label} must be a regular file")
    return resolved


def _verify_oracle_custody(oracle: Path) -> None:
    """Require a singly-linked, owner-owned file in an owner-only directory."""
    if os.name != "posix":
        return

    oracle_stat = oracle.stat()
    if oracle_stat.st_uid != os.geteuid():
        raise EvaluatorBoundaryError("oracle file must be owned by the evaluator user")
    if oracle_stat.st_nlink != 1:
        raise EvaluatorBoundaryError("oracle file must not have additional hard links")

    file_mode = stat.S_IMODE(oracle_stat.st_mode)
    if file_mode & 0o077 or not file_mode & stat.S_IRUSR:
        raise EvaluatorBoundaryError("oracle file must be owner-readable and inaccessible to group/other")

    parent = oracle.parent
    parent_stat = parent.stat()
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise EvaluatorBoundaryError("oracle parent must be a directory")
    if parent_stat.st_uid != os.geteuid():
        raise EvaluatorBoundaryError("oracle parent directory must be owned by the evaluator user")
    if stat.S_IMODE(parent_stat.st_mode) & 0o077:
        raise EvaluatorBoundaryError("oracle parent directory must be owner-only (0700)")


def verify_evaluator_boundary(
    workspace: str | Path,
    candidate_path: str | Path,
    oracle_path: str | Path,
) -> BoundaryEvidence:
    """Verify candidate visibility and oracle separation without reading oracle data."""
    workspace_path = Path(workspace).resolve(strict=True)
    if not workspace_path.is_dir():
        raise EvaluatorBoundaryError("workspace must be a directory")

    candidate_input = Path(candidate_path)
    if not candidate_input.is_absolute():
        candidate_input = workspace_path / candidate_input
    candidate = _resolve_without_symlinks(candidate_input, "candidate artifact")
    if not _inside(candidate, workspace_path):
        raise EvaluatorBoundaryError("candidate artifact must be inside the agent workspace")

    oracle_input = Path(oracle_path)
    if not oracle_input.is_absolute():
        raise EvaluatorBoundaryError("oracle path must be absolute and evaluator-provisioned")
    oracle = _resolve_without_symlinks(oracle_input, "oracle file")
    if _inside(oracle, workspace_path):
        raise EvaluatorBoundaryError("oracle file must be outside the agent workspace")

    _verify_oracle_custody(oracle)

    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return BoundaryEvidence(candidate, oracle, digest)


def validate_candidate_continuity(candidate: object) -> str:
    """Require proposal, validation, and plan to refer to the same immutable candidate."""
    if not isinstance(candidate, dict) or candidate.get("no_apply") is not True:
        raise EvaluatorBoundaryError("candidate must explicitly declare no_apply=true")
    phases = candidate.get("phases")
    if not isinstance(phases, dict):
        raise EvaluatorBoundaryError("candidate phases must be an object")
    hashes = []
    for phase in ("proposal", "validation", "plan"):
        record = phases.get(phase)
        if not isinstance(record, dict) or not isinstance(record.get("candidate_sha256"), str):
            raise EvaluatorBoundaryError(f"{phase} phase must include candidate_sha256")
        digest = record["candidate_sha256"]
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise EvaluatorBoundaryError(f"{phase} candidate hash is malformed")
        hashes.append(digest)
    if len(set(hashes)) != 1:
        raise EvaluatorBoundaryError("proposal, validation, and plan candidate hashes differ")
    if candidate.get("apply_invoked", False) is not False:
        raise EvaluatorBoundaryError("apply must not be invoked during evaluation")
    return hashes[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the E-007 evaluator trust boundary")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--oracle", required=True)
    args = parser.parse_args(argv)
    evidence = verify_evaluator_boundary(args.workspace, args.candidate, args.oracle)
    print(json.dumps(evidence.public_summary(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
