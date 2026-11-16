"""Verify a runner-only pilot schedule against the exact clean checkout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from schedule import ScheduleError, verify_schedule_checkout

MAX_SCHEDULE_BYTES = 16 * 1024 * 1024


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScheduleError("schedule_json_duplicate_key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise ScheduleError("schedule_json_non_finite_number")


def load_schedule(path: str | Path) -> dict:
    schedule_path = Path(path)
    try:
        if schedule_path.stat().st_size > MAX_SCHEDULE_BYTES:
            raise ScheduleError("schedule_file_too_large")
        raw = schedule_path.read_bytes()
    except ScheduleError:
        raise
    except OSError as error:
        raise ScheduleError("schedule_file_unavailable") from error
    if len(raw) > MAX_SCHEDULE_BYTES:
        raise ScheduleError("schedule_file_too_large")
    try:
        schedule = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except UnicodeDecodeError as error:
        raise ScheduleError("schedule_file_invalid_utf8") from error
    except json.JSONDecodeError as error:
        raise ScheduleError("schedule_file_invalid_json") from error
    if not isinstance(schedule, dict):
        raise ScheduleError("schedule_document_must_be_object")
    return schedule


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True, type=Path)
    args = parser.parse_args()
    try:
        schedule = load_schedule(args.schedule)
        verify_schedule_checkout(schedule)
    except ScheduleError as error:
        parser.error(str(error))

    print(json.dumps({
        "verified": True,
        "plan_id": schedule["plan_id"],
        "source_revision": schedule["protocol"]["source_revision"],
        "pairs": schedule["protocol"]["pairs"],
        "trials": len(schedule["trials"]),
    }, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
