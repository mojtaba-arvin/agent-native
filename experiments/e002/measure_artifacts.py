#!/usr/bin/env python3
"""Measure uncompressed Linux deployable payloads for the E-002 runtime arms.

The measurement includes each application payload plus dynamically linked ELF
dependencies discovered with ldd. WASI is measured as component + Wasmtime;
BEAM is measured as a production Mix release (including ERTS) plus its ELF
dependencies. This is a Linux x86_64 package-size diagnostic, not a universal
cross-platform binary comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Iterable


class ArtifactMeasurementError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_file_entries(paths: Iterable[Path], root: Path | None = None) -> list[dict]:
    entries = []
    seen_inodes = set()
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError as error:
            raise ArtifactMeasurementError(f"cannot_stat_payload_file:{path}") from error
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen_inodes:
            continue
        seen_inodes.add(identity)
        try:
            display = str(path.relative_to(root)) if root else str(path)
        except ValueError:
            display = str(path)
        entries.append({
            "path": display,
            "bytes": stat.st_size,
            "sha256": _sha256(path),
        })
    return entries


def payload_files(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    if not path.exists():
        raise ArtifactMeasurementError(f"artifact_path_missing:{path}")
    if path.is_file():
        return [path]
    if path.is_dir():
        return [item for item in path.rglob("*") if item.is_file()]
    raise ArtifactMeasurementError(f"artifact_path_not_file_or_directory:{path}")


def _elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == bytes((127,)) + b"ELF"
    except OSError as error:
        raise ArtifactMeasurementError(f"cannot_read_artifact:{path}") from error


def elf_dependencies(path: Path) -> list[Path]:
    """Return resolved shared dependencies for one ELF object."""
    completed = subprocess.run(
        ["ldd", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout or "") + "\\n" + (completed.stderr or "")
    if "not a dynamic executable" in output or "statically linked" in output:
        return []
    if completed.returncode != 0:
        raise ArtifactMeasurementError(
            f"ldd_failed_for:{path}:exit={completed.returncode}:{output.strip()[:500]}"
        )
    dependencies = set()
    for line in output.splitlines():
        if "not found" in line:
            raise ArtifactMeasurementError(f"unresolved_elf_dependency:{path}:{line.strip()}")
        match = re.search(r"=>\\s+(/[^\\s]+)", line)
        candidate = match.group(1) if match else None
        if candidate is None:
            first = line.strip().split(maxsplit=1)[0] if line.strip() else ""
            if first.startswith("/"):
                candidate = first
        if candidate:
            resolved = Path(candidate).resolve()
            if not resolved.is_file():
                raise ArtifactMeasurementError(f"missing_elf_dependency:{path}:{resolved}")
            dependencies.add(resolved)
    return sorted(dependencies, key=str)


def measure_candidate(name: str, kind: str, inputs: list[tuple[str, Path]]) -> dict:
    input_manifest = []
    elf_files = []
    for role, raw_path in inputs:
        resolved = raw_path.expanduser().resolve()
        files = payload_files(resolved)
        entries = _unique_file_entries(files, root=resolved if resolved.is_dir() else None)
        input_manifest.append({
            "role": role,
            "source": str(resolved),
            "file_count": len(entries),
            "bytes": sum(item["bytes"] for item in entries),
            "files": entries,
        })
        elf_files.extend(path for path in files if _elf(path))

    dependencies = set()
    for binary in sorted(set(elf_files), key=str):
        dependencies.update(elf_dependencies(binary))
    dep_manifest = _unique_file_entries(dependencies)
    app_bytes = sum(item["bytes"] for item in input_manifest)
    dependency_bytes = sum(item["bytes"] for item in dep_manifest)
    return {
        "candidate": name,
        "packaging_kind": kind,
        "application_and_runtime_payload_bytes": app_bytes,
        "external_shared_dependency_bytes": dependency_bytes,
        "estimated_uncompressed_deployable_payload_bytes": app_bytes + dependency_bytes,
        "input_artifacts": input_manifest,
        "external_dependencies": dep_manifest,
    }


def build_report(args: argparse.Namespace) -> dict:
    host = platform.uname()
    candidates = [
        measure_candidate("go-net-http", "native executable + resolved ELF dependencies",
                          [("application", args.go)]),
        measure_candidate("rust-tokio-hyper", "native executable + resolved ELF dependencies",
                          [("application", args.rust)]),
        measure_candidate("wasi-p2-wasmtime", "WASI component + Wasmtime runtime + resolved ELF dependencies",
                          [("component", args.wasi_component), ("runtime", args.wasmtime)]),
        measure_candidate("beam-elixir-otp", "production Mix release including ERTS + resolved ELF dependencies",
                          [("release", args.beam_release)]),
    ]
    return {
        "schema_version": 1,
        "measurement": "uncompressed Linux payload bytes plus resolved ldd shared dependencies",
        "host": {
            "system": host.system,
            "release": host.release,
            "machine": host.machine,
            "python": platform.python_version(),
        },
        "comparison_limitations": [
            "This is a Linux host-specific deployable-payload estimate, not a portable cross-platform package size.",
            "Go and Rust include the application executable and every ldd-resolved ELF dependency.",
            "WASI includes the component, the selected Wasmtime executable, and every ldd-resolved ELF dependency of that runtime.",
            "BEAM includes the production Mix release with its bundled ERTS and every ldd-resolved ELF dependency of ELF objects inside the release.",
            "Kernel, container base image, system configuration, CA roots, and OS service management are excluded.",
            "The packaging formats and runtime startup/operations characteristics remain different; this measurement alone cannot rank candidates or select a runtime.",
        ],
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", type=Path, required=True)
    parser.add_argument("--rust", type=Path, required=True)
    parser.add_argument("--wasi-component", type=Path, required=True)
    parser.add_argument("--wasmtime", type=Path, required=True)
    parser.add_argument("--beam-release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_report(args)
    except (OSError, ArtifactMeasurementError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        item["candidate"]: item["estimated_uncompressed_deployable_payload_bytes"]
        for item in report["candidates"]
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
