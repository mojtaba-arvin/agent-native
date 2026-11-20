#!/usr/bin/env python3
"""Safely restore and verify a T16 evidence release asset for PR acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT_FILES = {
    "prereg.json", "host.json", "protocol.json", "ledger.jsonl",
    "results.json", "report.md", "evidence-manifest.json",
}
REQUIRED_EVIDENCE = ROOT_FILES - {"evidence-manifest.json"}
MAX_MEMBER_BYTES = 1_000_000_000
MAX_TOTAL_BYTES = 1_500_000_000


def _safe_member(name: str) -> PurePosixPath:
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("unsafe_path_in_t16_evidence_archive")
    if relative.parts[0] in ROOT_FILES:
        if len(relative.parts) != 1:
            raise ValueError("nested_root_evidence_path")
    elif relative.parts[0] == "runs":
        if len(relative.parts) < 3 or Path(relative.name).suffix not in {".json", ".jsonl"}:
            raise ValueError("invalid_run_evidence_path")
    else:
        raise ValueError("unexpected_t16_evidence_archive_path")
    return relative


def restore_evidence(archive_path: Path, target: Path, expected_source_sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source_sha):
        raise ValueError("invalid_expected_source_sha")
    target.mkdir(parents=True, exist_ok=True)
    target = target.resolve()
    extracted: set[str] = set()
    total_size = 0

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            relative = _safe_member(member.name)
            if member.name in extracted or not member.isfile() or member.issym() or member.islnk():
                raise ValueError("duplicate_or_unsupported_t16_evidence_member")
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise ValueError("t16_evidence_member_size_limit")
            total_size += member.size
            if total_size > MAX_TOTAL_BYTES:
                raise ValueError("t16_evidence_archive_size_limit")
            destination = (target / Path(*relative.parts)).resolve()
            if not destination.is_relative_to(target):
                raise ValueError("t16_evidence_path_escapes_destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("missing_t16_evidence_member_data")
            destination.write_bytes(source.read())
            extracted.add(member.name)

    manifest_path = target / "evidence-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing_t16_evidence_manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("task") != "T16":
        raise ValueError("unsupported_t16_evidence_manifest")
    if manifest.get("source_sha") != expected_source_sha:
        raise ValueError("t16_evidence_not_bound_to_pr_head")

    files = manifest.get("files")
    if not isinstance(files, dict) or not REQUIRED_EVIDENCE.issubset(files):
        raise ValueError("incomplete_t16_evidence_manifest")
    actual_files = extracted - {"evidence-manifest.json"}
    if actual_files != set(files):
        raise ValueError("unmanifested_or_missing_t16_evidence_files")

    for relative_name, expected_digest in files.items():
        relative = _safe_member(relative_name)
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected_digest)):
            raise ValueError("invalid_t16_evidence_digest")
        path = (target / Path(*relative.parts)).resolve()
        if not path.is_relative_to(target) or not path.is_file():
            raise ValueError("missing_or_unsafe_t16_evidence_file")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
            raise ValueError("t16_evidence_sha256_mismatch:" + relative_name)

    prereg = json.loads((target / "prereg.json").read_text(encoding="utf-8"))
    results = json.loads((target / "results.json").read_text(encoding="utf-8"))
    protocol = json.loads((target / "protocol.json").read_text(encoding="utf-8"))
    prereg_hash = manifest.get("prereg_hash")
    canonical = {key: value for key, value in prereg.items() if key != "sha256"}
    canonical_bytes = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    actual_prereg_hash = hashlib.sha256(canonical_bytes).hexdigest()
    if prereg.get("source_sha") != expected_source_sha or prereg.get("sha256") != prereg_hash or actual_prereg_hash != prereg_hash:
        raise ValueError("t16_preregistration_binding_mismatch")
    if results.get("source_sha") != expected_source_sha or results.get("prereg_hash") != prereg_hash:
        raise ValueError("t16_results_binding_mismatch")
    if protocol.get("source_sha") != expected_source_sha:
        raise ValueError("t16_protocol_source_sha_mismatch")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("source_sha")
    args = parser.parse_args()
    manifest = restore_evidence(args.archive, args.target, args.source_sha)
    print(f"Restored and verified {len(manifest['files'])} T16 evidence files for {args.source_sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
