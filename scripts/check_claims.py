#!/usr/bin/env python3
"""Fail closed when a completion claim lacks immutable successful run evidence."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROGRESS = ROOT / "project-control" / "PROGRESS.json"
DEFAULT_LEDGER = ROOT / "project-control" / "RUN_LEDGER.jsonl"
ACCEPTED_OUTCOMES = {
    "all_layers_passed_on_pr_head",
    "observed_green",
    "passed",
    "passed_with_optimization",
    "success",
}


def _has_immutable_reference(value: Any) -> bool:
    """Accept a GitHub run ID, a full Git commit SHA, or a durable HTTP(S) URL."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "run_id" and type(item) is int and item > 0:
                return True
            if key in {"commit", "commit_sha", "head_sha", "sha", "blob_sha"}:
                if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{40}", item):
                    return True
            if key in {"url", "artifact_url"}:
                if isinstance(item, str) and re.fullmatch(
                    r"https://github\.com/[^/]+/[^/]+/actions/runs/\d+(?:/artifacts/\d+)?",
                    item,
                ):
                    return True
            if _has_immutable_reference(item):
                return True
    elif isinstance(value, list):
        return any(_has_immutable_reference(item) for item in value)
    return False


def validate_claims(progress: dict[str, Any], ledger_text: str) -> list[str]:
    errors: list[str] = []
    claims = progress.get("completion_claims")
    if not isinstance(claims, list):
        return ["PROGRESS.json: completion_claims must be an array"]

    events: dict[str, dict[str, Any]] = {}
    for line_no, raw in enumerate(ledger_text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(event, dict):
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: event must be an object")
            continue
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: event_id is required")
            continue
        if event_id in events:
            errors.append(f"RUN_LEDGER.jsonl:{line_no}: duplicate event_id {event_id}")
            continue
        events[event_id] = event

    claim_ids: set[str] = set()
    criterion_claims: set[tuple[str, str]] = set()
    milestones = progress.get("milestones")
    if not isinstance(milestones, dict):
        errors.append("PROGRESS.json: milestones must be an object")
        milestones = {}
    for index, claim in enumerate(claims):
        prefix = f"completion_claims[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{prefix}: claim must be an object")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            errors.append(f"{prefix}: id is required")
        elif claim_id in claim_ids:
            errors.append(f"{prefix}: duplicate claim id {claim_id}")
        else:
            claim_ids.add(claim_id)
        if not isinstance(claim.get("statement"), str) or not claim["statement"].strip():
            errors.append(f"{prefix}: statement is required")
        if claim.get("status") not in {"verified", "accepted"}:
            errors.append(f"{prefix}: status must be verified or accepted")
        milestone_id = claim.get("milestone_id")
        criterion = claim.get("criterion")
        if milestone_id is not None or criterion is not None:
            if not isinstance(milestone_id, str) or not isinstance(criterion, str):
                errors.append(f"{prefix}: milestone_id and criterion must be supplied together as strings")
            else:
                key = (milestone_id, criterion)
                if key in criterion_claims:
                    errors.append(f"{prefix}: duplicate claim for {milestone_id} criterion")
                criterion_claims.add(key)
                milestone = milestones.get(milestone_id)
                if not isinstance(milestone, dict):
                    errors.append(f"{prefix}: unknown milestone {milestone_id}")
                elif criterion not in milestone.get("verified_exit_criteria", []):
                    errors.append(f"{prefix}: claim maps to a criterion not marked verified")
        references = claim.get("evidence_event_ids")
        if not isinstance(references, list) or not references:
            errors.append(f"{prefix}: at least one evidence_event_id is required")
            continue
        if not all(isinstance(event_id, str) and event_id.strip() for event_id in references):
            errors.append(f"{prefix}: evidence_event_ids must contain non-empty strings")
            continue
        if len(references) != len(set(references)):
            errors.append(f"{prefix}: duplicate evidence_event_ids")
        for event_id in references:
            event = events.get(event_id)
            if event is None:
                errors.append(f"{prefix}: unknown evidence event {event_id}")
                continue
            if event.get("outcome") not in ACCEPTED_OUTCOMES:
                errors.append(f"{prefix}: evidence event {event_id} has non-acceptance outcome {event.get('outcome')!r}")
            if not _has_immutable_reference(event.get("evidence", [])):
                errors.append(f"{prefix}: evidence event {event_id} has no immutable run, commit, or URL reference")

    for milestone_id, milestone in milestones.items():
        if not isinstance(milestone, dict):
            errors.append(f"milestones.{milestone_id}: record must be an object")
            continue
        verified = milestone.get("verified_exit_criteria", [])
        if not isinstance(verified, list):
            errors.append(f"milestones.{milestone_id}: verified_exit_criteria must be an array")
            continue
        for criterion in verified:
            if (milestone_id, criterion) not in criterion_claims:
                errors.append(
                    f"milestones.{milestone_id}: verified criterion lacks an evidence-backed completion claim: {criterion}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    try:
        progress = json.loads(args.progress.read_text(encoding="utf-8"))
        ledger = args.ledger.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"CLAIMS INVALID: {exc}", file=sys.stderr)
        return 1
    if not isinstance(progress, dict):
        print("CLAIMS INVALID: PROGRESS.json must contain an object", file=sys.stderr)
        return 1
    errors = validate_claims(progress, ledger)
    if errors:
        print("CLAIMS INVALID:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"CLAIMS VALID: {len(progress['completion_claims'])} completion claim(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
