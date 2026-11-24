#!/usr/bin/env python3
"""Fetch and safely verify the T16 evidence release bound to the current PR head."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

ROOT_FILES = {
    "prereg.json", "host.json", "protocol.json", "ledger.jsonl",
    "results.json", "report.md", "execution.log", "preflight.log",
    "execution-metadata.json", "image-lock.json", "checksums.sha256",
    "evidence-manifest.json",
}
REQUIRED_FILES = {
    "prereg.json", "host.json", "protocol.json", "ledger.jsonl",
    "results.json", "report.md", "evidence-manifest.json", "checksums.sha256",
}
MAX_MEMBER_BYTES = 1_000_000_000
MAX_TOTAL_BYTES = 1_500_000_000


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in name:
        raise ValueError("unsafe_path_in_t16_evidence_archive")
    if len(path.parts) == 1 and path.parts[0] in ROOT_FILES:
        return path
    if (
        len(path.parts) == 3
        and path.parts[0] == "runs"
        and path.parts[1] in {"go-net-http", "rust-tokio-hyper"}
        and re.fullmatch(r"rep-[0-9]{2}\.(json|jsonl)", path.parts[2])
    ):
        return path
    raise ValueError("unexpected_t16_evidence_archive_path")


def restore_evidence(archive_path: Path, target: Path, expected_source_sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_source_sha):
        raise ValueError("invalid_expected_source_sha")
    target = target.resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    extracted: set[str] = set()
    total_size = 0
    archive_run_id: str | None = None

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            raw = PurePosixPath(member.name)
            if raw.is_absolute() or not raw.parts or ".." in raw.parts or "\\" in member.name:
                raise ValueError("unsafe_path_in_t16_evidence_archive")
            if len(raw.parts) < 3 or raw.parts[0] != "T16":
                raise ValueError("unexpected_t16_evidence_archive_prefix")
            run_id = raw.parts[1]
            if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", run_id):
                raise ValueError("invalid_t16_evidence_run_id")
            if archive_run_id is None:
                archive_run_id = run_id
            elif archive_run_id != run_id:
                raise ValueError("multiple_t16_run_ids_in_archive")
            relative = _safe_relative(PurePosixPath(*raw.parts[2:]).as_posix())

            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError("unsupported_t16_evidence_archive_member")
            if member.size < 0 or member.size > MAX_MEMBER_BYTES:
                raise ValueError("t16_evidence_member_size_limit")
            total_size += member.size
            if total_size > MAX_TOTAL_BYTES:
                raise ValueError("t16_evidence_archive_size_limit")
            relative_name = relative.as_posix()
            if relative_name in extracted:
                raise ValueError("duplicate_t16_evidence_archive_member")
            destination = (target / Path(*relative.parts)).resolve()
            if not destination.is_relative_to(target):
                raise ValueError("t16_evidence_path_escapes_destination")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError("missing_t16_evidence_member_data")
            with source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted.add(relative_name)

    if archive_run_id is None:
        raise ValueError("empty_t16_evidence_archive")
    manifest_path = target / "evidence-manifest.json"
    if not manifest_path.is_file():
        raise ValueError("missing_t16_evidence_manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 1
        or manifest.get("task") != "T16"
        or manifest.get("run_id") != archive_run_id
        or manifest.get("source_sha") != expected_source_sha
    ):
        raise ValueError("t16_evidence_manifest_binding_mismatch")

    files = manifest.get("files")
    if not isinstance(files, dict) or not REQUIRED_FILES - {"evidence-manifest.json"} <= set(files):
        raise ValueError("incomplete_t16_evidence_manifest")
    if extracted != set(files):
        raise ValueError("unmanifested_or_missing_t16_evidence_files")

    for relative_name, expected_digest in files.items():
        relative = _safe_relative(relative_name)
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
    if (
        prereg.get("source_sha") != expected_source_sha
        or prereg.get("sha256") != prereg_hash
        or actual_prereg_hash != prereg_hash
    ):
        raise ValueError("t16_preregistration_binding_mismatch")
    if results.get("source_sha") != expected_source_sha or results.get("prereg_hash") != prereg_hash:
        raise ValueError("t16_results_binding_mismatch")
    if results.get("image_ref") != manifest.get("image_ref"):
        raise ValueError("t16_results_image_binding_mismatch")
    if protocol.get("source_sha") != expected_source_sha:
        raise ValueError("t16_protocol_source_sha_mismatch")
    return manifest


def expected_sha_from_event(event_path: str | None) -> str:
    if event_path:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pull = event.get("pull_request")
        head = pull.get("head") if isinstance(pull, dict) else None
        sha = head.get("sha") if isinstance(head, dict) else None
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha
    sha = os.getenv("T16_EXPECTED_SOURCE_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", sha):
        return sha
    raise RuntimeError("T16 acceptance requires pull_request.head.sha or T16_EXPECTED_SOURCE_SHA")


def find_release_asset(repository: str, source_sha: str) -> str:
    api = "https://api.github.com/repos/%s/releases" % repository
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "agent-native-t16-evidence-verifier",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    matches = []
    for page in range(1, 11):
        url = api + "?per_page=100&page=" + str(page)
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=30) as response:
            releases = json.loads(response.read())
        if not releases:
            break
        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue
            if not str(release.get("tag_name", "")).startswith("t16-run-"):
                continue
            if release.get("target_commitish") != source_sha:
                continue
            if "Source: " + source_sha not in str(release.get("body", "")):
                continue
            for asset in release.get("assets", []):
                if (
                    str(asset.get("name", "")).startswith("t16-evidence-")
                    and str(asset.get("name", "")).endswith(".tar.gz")
                    and asset.get("state") == "uploaded"
                    and asset.get("browser_download_url")
                ):
                    matches.append((str(release.get("published_at", "")), asset["browser_download_url"]))
        if len(releases) < 100:
            break
    if not matches:
        raise RuntimeError("no uploaded T16 evidence release is bound to PR head " + source_sha)
    matches.sort(reverse=True)
    return matches[0][1]


def restore_for_current_pr(target: Path, repository: str, event_path: str | None) -> dict[str, Any]:
    source_sha = expected_sha_from_event(event_path)
    asset_url = find_release_asset(repository, source_sha)
    request = urllib.request.Request(asset_url, headers={"User-Agent": "agent-native-t16-evidence-verifier"})
    fd, archive_name = tempfile.mkstemp(prefix="t16-acceptance-", suffix=".tar.gz")
    total = 0
    try:
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=900) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_TOTAL_BYTES:
                    raise RuntimeError("T16 evidence release asset exceeds the download size limit")
                output.write(chunk)
        return restore_evidence(Path(archive_name), target, source_sha)
    finally:
        Path(archive_name).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=Path("experiments/e002/t16/evidence/restored"))
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", "mojtaba-arvin/agent-native"))
    parser.add_argument("--event-path", default=os.getenv("GITHUB_EVENT_PATH"))
    parser.add_argument("--expected-source-sha", default=os.getenv("T16_EXPECTED_SOURCE_SHA"))
    args = parser.parse_args()
    if args.expected_source_sha:
        os.environ["T16_EXPECTED_SOURCE_SHA"] = args.expected_source_sha
    manifest = restore_for_current_pr(args.target, args.repository, args.event_path)
    print("Restored and verified T16 run %s for source %s." % (manifest["run_id"], manifest["source_sha"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
