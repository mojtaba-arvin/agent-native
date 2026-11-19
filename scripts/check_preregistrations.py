#!/usr/bin/env python3
"""Fail-closed validation for preregistered cohorts and append-only decision events."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_STATUSES = {
    "draft",
    "frozen",
    "ready_for_manual_dispatch",
    "dispatched",
    "completed",
    "failed",
    "cancelled",
    "ineligible",
    "historical",
}
RUN_REQUIRED_STATUSES = {"dispatched", "completed", "failed", "cancelled", "ineligible"}


def git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def event_hash(event: dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "event_hash"}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path}: cannot read valid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path}: top-level value must be an object")
        return {}
    return value


def _load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{path}: cannot read JSONL: {exc}")
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_number}: invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path}:{line_number}: event must be an object")
            continue
        events.append(value)
    return events


def _safe_repo_path(root: Path, raw_path: Any, errors: list[str], label: str) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(f"{label}: path must be a non-empty repository-relative string")
        return None
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{label}: path escapes repository root")
        return None
    resolved = (root / relative).resolve()
    if root.resolve() not in resolved.parents:
        errors.append(f"{label}: path escapes repository root")
        return None
    if not resolved.is_file():
        errors.append(f"{label}: referenced file does not exist: {raw_path}")
        return None
    return resolved


def _validate_events(
    root: Path, events: list[dict[str, Any]], errors: list[str]
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    previous: dict[str, Any] | None = None
    required = {
        "event_id",
        "timestamp",
        "previous_event_hash",
        "previous_decision_file_blob_sha1",
        "previous_decision_log_blob_sha1",
        "previous_preregistrations_blob_sha1",
        "decision_file_blob_sha1",
        "decision_log_blob_sha1",
        "preregistrations_blob_sha1",
        "rationale",
        "affected_decision_ids",
        "affected_preregistration_ids",
        "evidence_ids",
        "event_hash",
    }
    for index, event in enumerate(events):
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            errors.append(f"decision event {index + 1}: event_id is required")
            continue
        if event_id in by_id:
            errors.append(f"decision event {event_id}: duplicate event_id")
        by_id[event_id] = event
        missing = sorted(required - event.keys())
        if missing:
            errors.append(f"decision event {event_id}: missing fields {', '.join(missing)}")
            continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, str):
            errors.append(f"decision event {event_id}: timestamp must be an ISO-8601 string")
        else:
            try:
                datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"decision event {event_id}: invalid ISO-8601 timestamp")
        if not isinstance(event.get("rationale"), str) or not event["rationale"].strip():
            errors.append(f"decision event {event_id}: rationale is required")
        for field in ("affected_decision_ids", "affected_preregistration_ids", "evidence_ids"):
            value = event.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                errors.append(f"decision event {event_id}: {field} must be an array of non-empty strings")
        for field in (
            "decision_file_blob_sha1",
            "decision_log_blob_sha1",
            "preregistrations_blob_sha1",
        ):
            value = event.get(field)
            if not isinstance(value, str) or not SHA1_RE.fullmatch(value):
                errors.append(f"decision event {event_id}: {field} must be a Git blob SHA-1")
        if "run_ledger_blob_sha1" in event or "previous_run_ledger_blob_sha1" in event:
            if "run_ledger_blob_sha1" not in event or "previous_run_ledger_blob_sha1" not in event:
                errors.append(f"decision event {event_id}: run-ledger pin fields must be supplied together")
            current_ledger_hash = event.get("run_ledger_blob_sha1")
            previous_ledger_hash = event.get("previous_run_ledger_blob_sha1")
            if not isinstance(current_ledger_hash, str) or not SHA1_RE.fullmatch(current_ledger_hash):
                errors.append(f"decision event {event_id}: run_ledger_blob_sha1 must be a Git blob SHA-1")
            if previous_ledger_hash is not None and (
                not isinstance(previous_ledger_hash, str) or not SHA1_RE.fullmatch(previous_ledger_hash)
            ):
                errors.append(f"decision event {event_id}: previous_run_ledger_blob_sha1 must be null or a Git blob SHA-1")
        digest = event.get("event_hash")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            errors.append(f"decision event {event_id}: event_hash must be SHA-256")
        elif digest != event_hash(event):
            errors.append(f"decision event {event_id}: event_hash does not match event content")

        if previous is None:
            for field in (
                "previous_event_hash",
                "previous_decision_file_blob_sha1",
                "previous_decision_log_blob_sha1",
                "previous_preregistrations_blob_sha1",
            ):
                if event.get(field) is not None:
                    errors.append(f"decision event {event_id}: first event {field} must be null")
            if "run_ledger_blob_sha1" in event and event.get("previous_run_ledger_blob_sha1") is not None:
                errors.append(f"decision event {event_id}: first run-ledger pin must have a null previous hash")
        else:
            if event.get("previous_event_hash") != previous.get("event_hash"):
                errors.append(f"decision event {event_id}: broken previous_event_hash chain")
            for previous_field, current_field in (
                ("previous_decision_file_blob_sha1", "decision_file_blob_sha1"),
                ("previous_decision_log_blob_sha1", "decision_log_blob_sha1"),
                ("previous_preregistrations_blob_sha1", "preregistrations_blob_sha1"),
            ):
                if event.get(previous_field) != previous.get(current_field):
                    errors.append(f"decision event {event_id}: {previous_field} does not match prior event")
            if "run_ledger_blob_sha1" in event:
                if event.get("previous_run_ledger_blob_sha1") != previous.get("run_ledger_blob_sha1"):
                    errors.append(f"decision event {event_id}: previous_run_ledger_blob_sha1 does not match prior event")
            elif "run_ledger_blob_sha1" in previous:
                errors.append(f"decision event {event_id}: run-ledger pin was dropped from the event chain")
        previous = event

    if not events:
        errors.append("DECISION_EVENTS.jsonl: at least one baseline event is required")
        return by_id

    latest = events[-1]
    current_files = {
        "decision_file_blob_sha1": root / "DECISIONS.json",
        "decision_log_blob_sha1": root / "research" / "design-decisions.md",
        "preregistrations_blob_sha1": root / "project-control" / "PREREGISTRATIONS.json",
    }
    for field, path in current_files.items():
        try:
            actual = git_blob_sha1(path)
        except OSError as exc:
            errors.append(f"{path}: cannot hash pinned file: {exc}")
            continue
        if latest.get(field) != actual:
            errors.append(
                f"{path}: current Git blob SHA-1 {actual} is not pinned by the latest decision event"
            )
    if "run_ledger_blob_sha1" in latest:
        run_ledger_path = root / "project-control" / "RUN_LEDGER.jsonl"
        try:
            actual = git_blob_sha1(run_ledger_path)
        except OSError as exc:
            errors.append(f"{run_ledger_path}: cannot hash pinned run ledger: {exc}")
        else:
            if latest.get("run_ledger_blob_sha1") != actual:
                errors.append(
                    f"{run_ledger_path}: current Git blob SHA-1 {actual} is not pinned by the latest decision event"
                )
    return by_id


def validate(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    registry_path = root / "project-control" / "PREREGISTRATIONS.json"
    event_path = root / "project-control" / "DECISION_EVENTS.jsonl"
    decision_path = root / "DECISIONS.json"
    registry = _load_json(registry_path, errors)
    decisions = _load_json(decision_path, errors)
    events = _load_jsonl(event_path, errors)
    event_by_id = _validate_events(root, events, errors)

    decision_records = decisions.get("decisions")
    if not isinstance(decision_records, list):
        errors.append("DECISIONS.json: decisions must be an array")
        known_decision_ids: set[str] = set()
    else:
        known_decision_ids = set()
        for index, decision in enumerate(decision_records):
            if not isinstance(decision, dict):
                errors.append(f"DECISIONS.json: decisions[{index}] must be an object")
                continue
            decision_id = decision.get("id")
            if not isinstance(decision_id, str) or not decision_id:
                errors.append(f"DECISIONS.json: decisions[{index}].id is required")
            elif decision_id in known_decision_ids:
                errors.append(f"DECISIONS.json: duplicate decision id {decision_id}")
            else:
                known_decision_ids.add(decision_id)
    for event in events:
        affected = event.get("affected_decision_ids", [])
        if isinstance(affected, list):
            unknown = [
                item for item in affected
                if isinstance(item, str) and item not in known_decision_ids
            ]
            if unknown:
                errors.append(
                    f"decision event {event.get('event_id')}: unknown decision IDs {', '.join(unknown)}"
                )

    if registry.get("schema_version") != 1:
        errors.append("PREREGISTRATIONS.json: schema_version must be 1")
    baseline_id = registry.get("baseline_event_id")
    if not isinstance(baseline_id, str) or baseline_id not in event_by_id:
        errors.append("PREREGISTRATIONS.json: baseline_event_id must reference a decision event")
    elif events and events[0].get("event_id") != baseline_id:
        errors.append("PREREGISTRATIONS.json: baseline_event_id must reference the first event")

    records = registry.get("records")
    if not isinstance(records, list):
        errors.append("PREREGISTRATIONS.json: records must be an array")
        return errors

    record_ids: set[str] = set()
    paths: set[str] = set()
    for index, record in enumerate(records):
        label = f"PREREGISTRATIONS.json: records[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{label}: record must be an object")
            continue
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"{label}: record_id is required")
            continue
        if record_id in record_ids:
            errors.append(f"{label}: duplicate record_id {record_id}")
        record_ids.add(record_id)
        kind = record.get("kind")
        if not isinstance(kind, str) or not kind:
            errors.append(f"{label}: kind is required")
        status = record.get("status")
        if not isinstance(status, str) or status not in ALLOWED_STATUSES:
            errors.append(f"{label}: unsupported status {status!r}")
        decision_event_id = record.get("decision_event_id")
        if not isinstance(decision_event_id, str) or decision_event_id not in event_by_id:
            errors.append(f"{label}: decision_event_id does not resolve to an event")
        raw_path = record.get("path")
        path = _safe_repo_path(root, raw_path, errors, label)
        if isinstance(raw_path, str):
            if raw_path in paths:
                errors.append(f"{label}: duplicate frozen path {raw_path}")
            paths.add(raw_path)
        expected_sha = record.get("git_blob_sha1")
        if status != "draft":
            if not isinstance(expected_sha, str) or not SHA1_RE.fullmatch(expected_sha):
                errors.append(f"{label}: frozen record requires a Git blob SHA-1")
            elif path is not None:
                actual_sha = git_blob_sha1(path)
                if actual_sha != expected_sha:
                    errors.append(
                        f"{label}: manifest hash changed (expected {expected_sha}, got {actual_sha}); create a new record ID and decision event"
                    )
        elif expected_sha is not None and (
            not isinstance(expected_sha, str) or not SHA1_RE.fullmatch(expected_sha)
        ):
            errors.append(f"{label}: draft git_blob_sha1, when supplied, must be a Git blob SHA-1")

        run_ids = record.get("run_ids", [])
        if not isinstance(run_ids, list) or any(
            isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0
            for run_id in run_ids
        ):
            errors.append(f"{label}: run_ids must be an array of positive integer IDs")
        elif len(run_ids) != len(set(run_ids)):
            errors.append(f"{label}: run_ids must not contain duplicates")
        elif isinstance(status, str) and status in RUN_REQUIRED_STATUSES and not run_ids:
            errors.append(f"{label}: status {status} requires at least one run ID")
        if status == "ready_for_manual_dispatch":
            if record.get("no_apply") is not True:
                errors.append(f"{label}: ready_for_manual_dispatch requires no_apply=true")
            if run_ids:
                errors.append(f"{label}: ready_for_manual_dispatch must not already contain run IDs")
        if isinstance(status, str) and kind == "cohort_manifest" and status in {
            "ready_for_manual_dispatch", "dispatched", "completed", "failed", "cancelled", "ineligible"
        } and record.get("no_apply") is not True:
            errors.append(f"{label}: agent cohort manifests must remain no-apply")

    known_record_ids = record_ids
    for event in events:
        affected = event.get("affected_preregistration_ids", [])
        if isinstance(affected, list):
            unknown = [item for item in affected if isinstance(item, str) and item not in known_record_ids]
            if unknown:
                errors.append(
                    f"decision event {event.get('event_id')}: unknown preregistration IDs {', '.join(unknown)}"
                )
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print("PREREGISTRATIONS VALID: pinned manifests and decision-event chain are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
