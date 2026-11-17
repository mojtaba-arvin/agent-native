"""Execute a complete immutable pilot schedule serially.

This is a runner for the disposable E-005 disclosure experiment, not a general
Agent Native runtime. Individual run directories remain the source of truth.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parent
ROOT = PILOT_ROOT.parents[1]
sys.path.insert(0, str(PILOT_ROOT))

from ollama_runner import run_one_trial, validate_local_ollama_url  # noqa: E402
from schedule import ScheduleError, verify_schedule_checkout  # noqa: E402
from verify_schedule import load_schedule  # noqa: E402


def _write_exclusive(path: Path, value: dict) -> None:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def _outside_checkout(path: str | Path, root: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    checkout = Path(root).resolve()
    try:
        resolved.relative_to(checkout)
    except ValueError:
        return resolved
    raise ValueError("batch_results_must_be_outside_checkout")


def _trial_summary(record: dict) -> dict:
    fields = (
        "sequence",
        "pair_id",
        "run_id",
        "candidate_id",
        "model_id",
        "status",
        "failure_class",
        "failure_detail",
        "agent_started_at_ns",
        "agent_finished_at_ns",
        "trace_path",
        "candidate_path",
        "candidate_sha256",
        "candidate_summary",
        "evaluator_status",
    )
    return {key: record.get(key) for key in fields}


def run_schedule(
    schedule: dict,
    *,
    results_dir: str | Path,
    base_url: str = "http://127.0.0.1:11434",
    root: str | Path = ROOT,
) -> dict:
    """Run trials serially, preserve each outcome, and write one batch manifest."""
    validate_local_ollama_url(base_url)
    verify_schedule_checkout(schedule, root=root)

    results_root = _outside_checkout(results_dir, root)
    results_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    plan_id = schedule["plan_id"]
    batch_path = results_root / f"batch-{plan_id}.json"
    if batch_path.exists():
        raise FileExistsError("batch_manifest_already_exists")

    protocol = schedule["protocol"]
    trials = schedule["trials"]
    started_at_ns = time.monotonic_ns()
    batch = {
        "schema_version": 1,
        "plan_id": plan_id,
        "source_revision": protocol["source_revision"],
        "model_id": protocol["model_id"],
        "scheduled_pairs": protocol["pairs"],
        "scheduled_trials": len(trials),
        "started_at_ns": started_at_ns,
        "finished_at_ns": None,
        "status": "running",
        "completed_trials": 0,
        "candidate_ready_count": 0,
        "failed_count": 0,
        "failure_counts": {},
        "trials": [],
        "runner_error": None,
        "batch_manifest_path": str(batch_path),
    }

    runner_error: Exception | None = None
    try:
        for expected_sequence, trial in enumerate(trials, 1):
            if trial.get("sequence") != expected_sequence:
                raise ScheduleError("trial_sequence_changed_after_schedule_validation")
            record = run_one_trial(
                trial,
                plan_id=plan_id,
                results_root=results_root,
                base_url=base_url,
                root=root,
            )
            summary = _trial_summary(record)
            batch["trials"].append(summary)
            batch["completed_trials"] += 1
            if record["status"] == "candidate_ready_for_external_evaluation":
                batch["candidate_ready_count"] += 1
            else:
                batch["failed_count"] += 1
                failure_class = record.get("failure_class") or "UNKNOWN_FAILURE"
                batch["failure_counts"][failure_class] = (
                    batch["failure_counts"].get(failure_class, 0) + 1
                )
        batch["status"] = "completed"
    except KeyboardInterrupt:
        batch["status"] = "interrupted"
        raise
    except Exception as error:
        runner_error = error
        batch["status"] = "interrupted"
        batch["runner_error"] = {
            "class": type(error).__name__,
            "detail": str(error)[:500],
        }
    finally:
        batch["finished_at_ns"] = time.monotonic_ns()
        _write_exclusive(batch_path, batch)

    batch["batch_manifest_path"] = str(batch_path)
    if runner_error is not None:
        raise RuntimeError(
            f"batch_interrupted_after_{batch['completed_trials']}_trials:"
            f"{type(runner_error).__name__}"
        ) from runner_error
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args()

    try:
        schedule_path = args.schedule.expanduser().resolve()
        _outside_checkout(schedule_path, ROOT)
        schedule = load_schedule(schedule_path)
        result = run_schedule(
            schedule,
            results_dir=args.results_dir,
            base_url=args.ollama_url,
        )
    except (ScheduleError, ValueError, OSError, RuntimeError) as error:
        print(f"BATCH_RUN_ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if result["status"] != "completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
