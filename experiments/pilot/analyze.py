"""Produce a paired, reproducible analysis of finalized pilot runs.

The analyzer refuses incomplete schedules and never silently drops missing runs.
It reports descriptive paired differences; it does not choose a framework design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parent
ROOT = PILOT_ROOT.parents[1]
E007_ROOT = PILOT_ROOT.parent / "e007"
sys.path.insert(0, str(PILOT_ROOT))
sys.path.insert(0, str(E007_ROOT))

from metrics import load_jsonl, summarize  # noqa: E402
from schedule import ScheduleError, verify_schedule_checkout  # noqa: E402
from verify_schedule import load_schedule  # noqa: E402

BOOTSTRAP_REPETITIONS = 10_000
BOOTSTRAP_SEED = 1729
PAIRED_METRICS = (
    "total_tokens",
    "tool_calls",
    "tool_errors",
    "schema_lookup_calls",
    "wall_clock_seconds",
    "repair_events",
)


class AnalysisError(ValueError):
    """Raised when a paired analysis cannot be reproduced from complete inputs."""


def _outside_checkout(path: str | Path, root: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    checkout = Path(root).resolve()
    try:
        resolved.relative_to(checkout)
    except ValueError:
        return resolved
    raise AnalysisError("analysis_artifacts_must_be_outside_checkout")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


def _bootstrap_interval(values: list[float]) -> dict | None:
    if not values:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    count = len(values)
    samples = []
    for _ in range(BOOTSTRAP_REPETITIONS):
        samples.append(statistics.mean(values[rng.randrange(count)] for _ in range(count)))
    samples.sort()
    lower = samples[int(0.025 * (BOOTSTRAP_REPETITIONS - 1))]
    upper = samples[int(0.975 * (BOOTSTRAP_REPETITIONS - 1))]
    return {"lower_95": lower, "upper_95": upper}


def _paired_difference(values: list[float]) -> dict | None:
    if not values:
        return None
    interval = _bootstrap_interval(values)
    return {
        "pairs": len(values),
        "mean_upfront_minus_progressive": statistics.mean(values),
        "median_upfront_minus_progressive": statistics.median(values),
        "bootstrap_95_percentile_interval": interval,
        "interpretation": "positive_means_upfront_higher",
    }


def _descriptive(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def _mcnemar_exact_two_sided(progressive: list[bool], upfront: list[bool]) -> dict:
    if len(progressive) != len(upfront):
        raise AnalysisError("paired_acceptance_vector_length_mismatch")
    upfront_only = sum(a and not p for p, a in zip(progressive, upfront, strict=True))
    progressive_only = sum(p and not a for p, a in zip(progressive, upfront, strict=True))
    discordant = upfront_only + progressive_only
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(discordant, index) for index in range(min(upfront_only, progressive_only) + 1))
        p_value = min(1.0, (2 * tail) / (2**discordant))
    return {
        "upfront_only_acceptances": upfront_only,
        "progressive_only_acceptances": progressive_only,
        "discordant_pairs": discordant,
        "exact_two_sided_p_value": p_value,
    }


def _arm_summary(rows: list[dict]) -> dict:
    eligible = [row for row in rows if row["eligible_for_acceptance"]]
    accepted = sum(row["accepted"] for row in eligible)
    return {
        "trials": len(rows),
        "eligible_trials": len(eligible),
        "infrastructure_exclusions": len(rows) - len(eligible),
        "accepted_trials": accepted,
        "acceptance_rate": accepted / len(eligible) if eligible else None,
        "median_input_tokens": _descriptive([
            row["input_tokens"] for row in eligible if row["input_tokens"] is not None
        ]),
        "median_output_tokens": _descriptive([
            row["output_tokens"] for row in eligible if row["output_tokens"] is not None
        ]),
        "median_total_tokens": _descriptive([
            row["total_tokens"] for row in eligible if row["total_tokens"] is not None
        ]),
        "median_tool_calls": _descriptive([row["tool_calls"] for row in eligible]),
        "median_tool_errors": _descriptive([row["tool_errors"] for row in eligible]),
        "median_schema_lookups": _descriptive([row["schema_lookup_calls"] for row in eligible]),
        "median_wall_clock_seconds": _descriptive([
            row["wall_clock_seconds"]
            for row in eligible
            if row["wall_clock_seconds"] is not None
        ]),
        "inference_cost_complete": bool(eligible) and all(row["cost_complete"] for row in eligible),
        "inference_cost_usd": (
            sum(row["inference_cost_usd"] for row in eligible)
            if eligible and all(row["cost_complete"] for row in eligible)
            else None
        ),
        "failure_classes": dict(sorted(
            (failure, sum(row["failure_class"] == failure for row in rows))
            for failure in {row["failure_class"] for row in rows if row["failure_class"]}
        )),
    }


def analyze_schedule(
    schedule: dict,
    *,
    results_dir: str | Path,
    output_path: str | Path,
    root: str | Path = ROOT,
) -> dict:
    """Analyze every scheduled finalized trace as one paired study."""
    verify_schedule_checkout(schedule, root=root)
    results_root = _outside_checkout(results_dir, root)
    output = _outside_checkout(output_path, root)

    expected_trials = schedule["trials"]
    expected_by_run = {trial["run_id"]: trial for trial in expected_trials}
    if len(expected_by_run) != len(expected_trials):
        raise AnalysisError("schedule_contains_duplicate_run_ids")

    all_events: list[dict] = []
    trace_hashes = {}
    for trial in expected_trials:
        run_dir = results_root / trial["run_id"]
        trace_path = run_dir / "finalized.jsonl"
        if not trace_path.is_file():
            raise AnalysisError(f"finalized_trace_missing:{trial['run_id']}")
        events = load_jsonl(trace_path)
        if not events:
            raise AnalysisError(f"finalized_trace_empty:{trial['run_id']}")
        for event in events:
            if (
                event.get("run_id") != trial["run_id"]
                or event.get("candidate_id") != trial["candidate_id"]
                or event.get("task_id") != trial["task_id"]
                or event.get("model_id") != trial["model_id"]
                or event.get("attempt") != trial["attempt"]
            ):
                raise AnalysisError(f"finalized_trace_identity_mismatch:{trial['run_id']}")
        finishes = [event for event in events if event["event_type"] == "task_finished"]
        if len(finishes) != 1:
            raise AnalysisError(f"finalized_trace_requires_one_finish:{trial['run_id']}")
        trace_hashes[trial["run_id"]] = _sha256_file(trace_path)
        all_events.extend(events)

    aggregate = summarize(all_events)
    rows_by_run = {row["run_id"]: row for row in aggregate["tasks"]}
    if set(rows_by_run) != set(expected_by_run):
        missing = sorted(set(expected_by_run) - set(rows_by_run))
        extra = sorted(set(rows_by_run) - set(expected_by_run))
        raise AnalysisError(f"trace_run_set_mismatch:missing={missing}:extra={extra}")

    rows_by_pair: dict[str, dict[str, dict]] = {}
    arm_rows = {"progressive": [], "upfront": []}
    for run_id, trial in expected_by_run.items():
        row = rows_by_run[run_id]
        if row.get("candidate_id") != trial["candidate_id"]:
            raise AnalysisError(f"trace_arm_mismatch:{run_id}")
        if row.get("model_id") != trial["model_id"]:
            raise AnalysisError(f"trace_model_mismatch:{run_id}")
        row = {**row, "pair_id": trial["pair_id"]}
        arm_rows[trial["candidate_id"]].append(row)
        rows_by_pair.setdefault(trial["pair_id"], {})[trial["candidate_id"]] = row

    paired_acceptance_progressive = []
    paired_acceptance_upfront = []
    excluded_acceptance_pairs = []
    paired_deltas = {metric: [] for metric in PAIRED_METRICS}
    metric_pair_counts = {metric: 0 for metric in PAIRED_METRICS}

    for pair_id, arms in sorted(rows_by_pair.items()):
        if set(arms) != {"progressive", "upfront"}:
            raise AnalysisError(f"paired_trial_missing_arm:{pair_id}")
        progressive = arms["progressive"]
        upfront = arms["upfront"]
        if progressive["eligible_for_acceptance"] and upfront["eligible_for_acceptance"]:
            paired_acceptance_progressive.append(progressive["accepted"])
            paired_acceptance_upfront.append(upfront["accepted"])
        else:
            excluded_acceptance_pairs.append(pair_id)

        for metric in PAIRED_METRICS:
            left, right = progressive.get(metric), upfront.get(metric)
            if left is not None and right is not None:
                paired_deltas[metric].append(float(right) - float(left))
                metric_pair_counts[metric] += 1

    acceptance_pairs = len(paired_acceptance_progressive)
    acceptance_difference = (
        _paired_difference([
            float(upfront) - float(progressive)
            for progressive, upfront in zip(
                paired_acceptance_progressive,
                paired_acceptance_upfront,
                strict=True,
            )
        ])
        if acceptance_pairs
        else None
    )

    result = {
        "analysis_version": 1,
        "plan_id": schedule["plan_id"],
        "source_revision": schedule["protocol"]["source_revision"],
        "model_id": schedule["protocol"]["model_id"],
        "scheduled_pairs": schedule["protocol"]["pairs"],
        "completed_pairs": len(rows_by_pair),
        "scheduled_trials": len(expected_trials),
        "completed_trials": len(rows_by_run),
        "bootstrap": {
            "method": "paired_percentile_bootstrap",
            "repetitions": BOOTSTRAP_REPETITIONS,
            "seed": BOOTSTRAP_SEED,
            "interval": "95_percent",
        },
        "by_arm": {
            "progressive": _arm_summary(arm_rows["progressive"]),
            "upfront": _arm_summary(arm_rows["upfront"]),
        },
        "paired_acceptance": {
            "eligible_pairs": acceptance_pairs,
            "infrastructure_excluded_pairs": excluded_acceptance_pairs,
            "upfront_minus_progressive": acceptance_difference,
            "mcnemar": _mcnemar_exact_two_sided(
                paired_acceptance_progressive,
                paired_acceptance_upfront,
            ),
        },
        "paired_effort_differences": {
            metric: {
                **(_paired_difference(paired_deltas[metric]) or {}),
                "n_pairs": metric_pair_counts[metric],
            }
            for metric in PAIRED_METRICS
        },
        "e007_aggregate": aggregate,
        "trace_sha256": trace_hashes,
    }

    _write_exclusive(output, result)
    result["analysis_output"] = str(output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schedule", required=True, type=Path)
    parser.add_argument("--results-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        schedule_path = _outside_checkout(args.schedule, ROOT)
        schedule = load_schedule(schedule_path)
        result = analyze_schedule(
            schedule,
            results_dir=args.results_dir,
            output_path=args.output,
        )
    except (AnalysisError, ScheduleError, OSError, ValueError) as error:
        print(f"ANALYSIS_ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)

    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
