#!/usr/bin/env python3
"""Generate an evidence scorecard from immutable CI, ledger, and progress inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _load_ledger(raw: bytes) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"run ledger is not UTF-8: {exc}") from exc
    events = []
    seen = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"run ledger line {line_number} is invalid JSON: {exc}") from exc
        if not isinstance(event, dict):
            raise ValueError(f"run ledger line {line_number} must be an object")
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise ValueError(f"run ledger line {line_number} has no event_id")
        if event_id in seen:
            raise ValueError(f"run ledger contains duplicate event_id: {event_id}")
        seen.add(event_id)
        events.append(event)
    return events


def _run_ids(event: dict[str, Any]) -> list[int]:
    found = set()
    evidence = event.get("evidence", [])
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            value = item.get("run_id")
            if type(value) is int and value > 0:
                found.add(value)
    return sorted(found)


def build_scorecard(summary_raw: bytes, ledger_raw: bytes, progress_raw: bytes) -> dict[str, Any]:
    summary = _load_json_bytes(summary_raw, "CI summary")
    progress = _load_json_bytes(progress_raw, "progress register")
    if type(summary.get("schema_version")) is not int or summary["schema_version"] != 1:
        raise ValueError("CI summary schema_version must be 1")

    source = summary.get("source")
    if not isinstance(source, dict):
        raise ValueError("CI summary source must be an object")
    run_id = source.get("workflow_run_id")
    attempt = source.get("workflow_run_attempt")
    commit_sha = source.get("commit_sha")
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("CI scorecards require a positive GitHub workflow run ID")
    if type(attempt) is not int or attempt <= 0:
        raise ValueError("CI scorecards require a positive workflow run attempt")
    if not isinstance(commit_sha, str) or not SHA1_RE.fullmatch(commit_sha):
        raise ValueError("CI scorecards require the exact 40-character source commit SHA")
    if not isinstance(source.get("branch"), str) or not source["branch"]:
        raise ValueError("CI scorecards require a source branch")
    if not isinstance(summary.get("generated_at_utc"), str):
        raise ValueError("CI summary generated_at_utc is required")

    suites = summary.get("suites")
    if not isinstance(suites, list):
        raise ValueError("CI summary suites must be an array")
    suite_names = set()
    normalized_suites = []
    for index, suite in enumerate(suites):
        if not isinstance(suite, dict):
            raise ValueError(f"CI suite {index} must be an object")
        name = suite.get("name")
        if not isinstance(name, str) or not name or name in suite_names:
            raise ValueError(f"CI suite {index} has a missing or duplicate name")
        suite_names.add(name)
        status = suite.get("status")
        if status not in {"passed", "failed"}:
            raise ValueError(f"CI suite {name} has an unsupported status")
        for field in ("test_count", "skipped_test_count", "exit_code"):
            if type(suite.get(field)) is not int or suite[field] < 0:
                raise ValueError(f"CI suite {name} has invalid {field}")
        if suite["skipped_test_count"] > suite["test_count"]:
            raise ValueError(f"CI suite {name} skipped count exceeds total tests")
        output_sha = suite.get("output_sha256")
        if not isinstance(output_sha, str) or not SHA256_RE.fullmatch(output_sha):
            raise ValueError(f"CI suite {name} has invalid output_sha256")
        normalized_suites.append({
            "name": name,
            "status": status,
            "exit_code": suite["exit_code"],
            "elapsed_seconds": suite.get("elapsed_seconds"),
            "test_count": suite["test_count"],
            "skipped_test_count": suite["skipped_test_count"],
            "output_sha256": output_sha,
        })

    passed = sum(item["status"] == "passed" for item in normalized_suites)
    failed = len(normalized_suites) - passed
    total_tests = sum(item["test_count"] for item in normalized_suites)
    skipped_tests = sum(item["skipped_test_count"] for item in normalized_suites)
    result = summary.get("result")
    counts = summary.get("test_counts")
    if not isinstance(result, dict) or not isinstance(counts, dict):
        raise ValueError("CI summary result and test_counts are required")
    expected_status = "passed" if failed == 0 else "failed"
    if result.get("status") != expected_status:
        raise ValueError("CI summary result status does not match suite outcomes")
    if result.get("passed_suites") != passed or result.get("failed_suites") != failed:
        raise ValueError("CI summary suite totals do not match individual suite results")
    if counts.get("total") != total_tests or counts.get("skipped") != skipped_tests:
        raise ValueError("CI summary test totals do not match individual suite counts")
    by_suite = counts.get("by_suite")
    expected_by_suite = {
        item["name"]: {
            "tests": item["test_count"],
            "skipped": item["skipped_test_count"],
        }
        for item in normalized_suites
    }
    if by_suite != expected_by_suite:
        raise ValueError("CI summary by-suite test counts do not match suite records")

    ledger_events = _load_ledger(ledger_raw)
    ledger_by_id = {event["event_id"]: event for event in ledger_events}
    claims = progress.get("completion_claims")
    if not isinstance(claims, list):
        raise ValueError("progress completion_claims must be an array")
    verified_claims = []
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("status") != "verified":
            continue
        claim_id = claim.get("id")
        evidence_ids = claim.get("evidence_event_ids")
        if not isinstance(claim_id, str) or not isinstance(evidence_ids, list) or not evidence_ids:
            raise ValueError("verified progress claims require an ID and evidence event IDs")
        missing = [item for item in evidence_ids if item not in ledger_by_id]
        if missing:
            raise ValueError(f"verified claim {claim_id} references missing ledger events: {', '.join(missing)}")
        verified_claims.append({
            "id": claim_id,
            "milestone_id": claim.get("milestone_id"),
            "criterion": claim.get("criterion"),
            "statement": claim.get("statement"),
            "evidence_event_ids": evidence_ids,
        })

    run_history = []
    for event in ledger_events:
        run_history.append({
            "event_id": event["event_id"],
            "timestamp": event.get("timestamp"),
            "kind": event.get("kind"),
            "outcome": event.get("outcome"),
            "task_id": event.get("task_id"),
            "run_ids": _run_ids(event),
            "summary": event.get("summary"),
            "limitations": event.get("limitations", []),
        })

    return {
        "schema_version": 1,
        "generated_at_utc": summary["generated_at_utc"],
        "source": {
            "repository": source.get("repository"),
            "workflow_run_id": run_id,
            "workflow_run_attempt": attempt,
            "commit_sha": commit_sha,
            "branch": source["branch"],
            "base_sha": source.get("base_sha"),
            "event_name": source.get("event_name"),
            "ci_summary_sha256": _sha256(summary_raw),
            "run_ledger_sha256": _sha256(ledger_raw),
            "progress_sha256": _sha256(progress_raw),
        },
        "ci_result": {
            "status": expected_status,
            "passed_suites": passed,
            "failed_suites": failed,
            "elapsed_seconds": result.get("elapsed_seconds"),
        },
        "test_counts": {
            "total": total_tests,
            "skipped": skipped_tests,
            "by_suite": expected_by_suite,
        },
        "suites": normalized_suites,
        "run_history": run_history,
        "verified_claims": verified_claims,
    }


def validate_scorecard(
    scorecard: dict[str, Any], summary_raw: bytes, ledger_raw: bytes, progress_raw: bytes
) -> None:
    expected = build_scorecard(summary_raw, ledger_raw, progress_raw)
    if _canonical(scorecard) != _canonical(expected):
        raise ValueError("scorecard differs from metrics derived from its pinned source artifacts")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--progress", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary_raw = args.summary.read_bytes()
    ledger_raw = args.ledger.read_bytes()
    progress_raw = args.progress.read_bytes()
    scorecard = build_scorecard(summary_raw, ledger_raw, progress_raw)
    validate_scorecard(scorecard, summary_raw, ledger_raw, progress_raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(scorecard, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"SCORECARD VALID: run {scorecard['source']['workflow_run_id']} "
        f"commit {scorecard['source']['commit_sha']} "
        f"{scorecard['test_counts']['total']} tests across {scorecard['ci_result']['passed_suites'] + scorecard['ci_result']['failed_suites']} suites"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
