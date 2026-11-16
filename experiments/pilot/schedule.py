"""Create deterministic, randomized paired trial schedules for the pilot.

The schedule is runner-only metadata. Never pass it to the agent. In particular,
candidate_id and disclosure_arm are treatment labels, not agent context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parent
ROOT = PILOT_ROOT.parents[1]
TASK_ID = "pilot-catalog-add-readonly-operation"
ARMS = ("progressive", "upfront")
SOURCE_FILES = (
    "experiments/pilot/TASK.md",
    "experiments/e001/examples/catalog.an",
    "experiments/e001/prototype/agent_native.py",
    "experiments/e005/interface.py",
    "experiments/e005/tools.json",
    "experiments/pilot/surface.py",
    "experiments/pilot/gateway.py",
    "experiments/pilot/candidate.py",
    "experiments/pilot/candidate.schema.json",
    "experiments/pilot/evaluation-result.schema.json",
    "experiments/pilot/finalize.py",
    "experiments/e007/trace.schema.json",
    "experiments/e007/metrics.py",
)
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ScheduleError(ValueError):
    """Raised when a trial schedule cannot be pinned reproducibly."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_source_files(root: str | Path = ROOT) -> dict[str, str]:
    base = Path(root)
    hashes = {}
    for relative in SOURCE_FILES:
        path = base / relative
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ScheduleError(f"source_file_unavailable:{relative}") from error
        hashes[relative] = sha256_bytes(raw)
    return hashes


def create_schedule(
    *,
    pairs: int,
    seed: int,
    model_id: str,
    source_revision: str,
    max_input_tokens: int,
    max_output_tokens: int,
    max_tool_calls: int,
    max_wall_seconds: int,
    root: str | Path = ROOT,
) -> dict:
    if type(pairs) is not int or not 1 <= pairs <= 500:
        raise ScheduleError("pairs_must_be_between_1_and_500")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ScheduleError("seed_must_be_unsigned_32_bit_integer")
    if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 256:
        raise ScheduleError("model_id_must_be_nonempty_and_at_most_256_chars")
    if not isinstance(source_revision, str) or not REVISION_PATTERN.fullmatch(source_revision):
        raise ScheduleError("source_revision_must_be_full_git_sha")
    budgets = {
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "max_tool_calls": max_tool_calls,
        "max_wall_seconds": max_wall_seconds,
    }
    for name, value in budgets.items():
        if type(value) is not int or value < 1:
            raise ScheduleError(f"{name}_must_be_positive_integer")

    source_hashes = hash_source_files(root)
    protocol = {
        "protocol_version": 1,
        "task_id": TASK_ID,
        "source_revision": source_revision,
        "source_sha256": source_hashes,
        "model_id": model_id.strip(),
        "budgets": budgets,
        "pairs": pairs,
        "seed": seed,
        "arms": list(ARMS),
        "randomization": "independent_uniform_order_within_each_pair",
        "execution": {
            "fresh_state_per_trial": True,
            "max_concurrent_trials": 1,
            "agent_receives_arm_label": False,
        },
    }
    plan_id = sha256_bytes(canonical_json(protocol))
    rng = random.Random(seed)
    trials = []
    sequence = 0
    for pair_number in range(1, pairs + 1):
        order = list(ARMS)
        rng.shuffle(order)
        pair_id = f"pair-{pair_number:04d}"
        for arm in order:
            sequence += 1
            run_material = f"{plan_id}:{pair_number}:{arm}".encode("utf-8")
            run_hash = sha256_bytes(run_material)
            trials.append({
                "sequence": sequence,
                "pair_id": pair_id,
                "run_id": f"{pair_id}-{arm}-{run_hash[:12]}",
                "candidate_id": arm,
                "model_id": protocol["model_id"],
                "task_id": TASK_ID,
                "attempt": 1,
                "source_revision": source_revision,
                "source_sha256": source_hashes,
                "budgets": budgets,
                "fresh_state_required": True,
                "agent_visible_treatment_label": False,
            })

    return {
        "schedule_version": 1,
        "plan_id": plan_id,
        "protocol": protocol,
        "trials": trials,
    }


def validate_schedule(schedule: Any) -> None:
    if not isinstance(schedule, dict) or set(schedule) != {
        "schedule_version", "plan_id", "protocol", "trials"
    }:
        raise ScheduleError("schedule_shape_invalid")
    if type(schedule["schedule_version"]) is not int or schedule["schedule_version"] != 1:
        raise ScheduleError("schedule_version_unsupported")
    protocol = schedule["protocol"]
    protocol_fields = {
        "protocol_version", "task_id", "source_revision", "source_sha256",
        "model_id", "budgets", "pairs", "seed", "arms", "randomization",
        "execution",
    }
    if not isinstance(protocol, dict) or set(protocol) != protocol_fields:
        raise ScheduleError("protocol_shape_invalid")
    expected_id = sha256_bytes(canonical_json(protocol))
    if schedule["plan_id"] != expected_id:
        raise ScheduleError("plan_id_mismatch")
    if protocol.get("protocol_version") != 1 or protocol.get("task_id") != TASK_ID:
        raise ScheduleError("protocol_identity_invalid")
    if protocol.get("arms") != list(ARMS):
        raise ScheduleError("protocol_arms_invalid")
    if protocol.get("randomization") != "independent_uniform_order_within_each_pair":
        raise ScheduleError("protocol_randomization_invalid")
    if protocol.get("execution") != {
        "fresh_state_per_trial": True,
        "max_concurrent_trials": 1,
        "agent_receives_arm_label": False,
    }:
        raise ScheduleError("protocol_execution_policy_invalid")
    if not isinstance(protocol.get("model_id"), str) or not protocol["model_id"]:
        raise ScheduleError("protocol_model_id_invalid")
    if not isinstance(protocol.get("source_revision"), str) or not REVISION_PATTERN.fullmatch(protocol["source_revision"]):
        raise ScheduleError("protocol_source_revision_invalid")
    source_hashes = protocol.get("source_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(SOURCE_FILES):
        raise ScheduleError("protocol_source_hashes_invalid")
    for relative, digest in source_hashes.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ScheduleError(f"protocol_source_hash_invalid:{relative}")
    budgets = protocol.get("budgets")
    if not isinstance(budgets, dict) or set(budgets) != {
        "max_input_tokens", "max_output_tokens", "max_tool_calls", "max_wall_seconds"
    }:
        raise ScheduleError("protocol_budgets_invalid")
    if any(type(value) is not int or value < 1 for value in budgets.values()):
        raise ScheduleError("protocol_budget_value_invalid")
    seed = protocol.get("seed")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ScheduleError("protocol_seed_invalid")
    pairs = protocol.get("pairs")
    if type(pairs) is not int or not 1 <= pairs <= 500:
        raise ScheduleError("protocol_pairs_invalid")
    trials = schedule["trials"]
    if not isinstance(trials, list) or len(trials) != pairs * 2:
        raise ScheduleError("trial_count_mismatch")

    seen_run_ids = set()
    seen_sequences = set()
    by_pair: dict[str, list[dict]] = {}
    trial_fields = {
        "sequence", "pair_id", "run_id", "candidate_id", "model_id",
        "task_id", "attempt", "source_revision", "source_sha256",
        "budgets", "fresh_state_required", "agent_visible_treatment_label",
    }
    for trial in trials:
        if not isinstance(trial, dict) or set(trial) != trial_fields:
            raise ScheduleError("trial_shape_invalid")
        if trial.get("candidate_id") not in ARMS:
            raise ScheduleError("trial_candidate_invalid")
        run_id = trial.get("run_id")
        if not isinstance(run_id, str) or run_id in seen_run_ids:
            raise ScheduleError("trial_run_id_missing_or_duplicate")
        seen_run_ids.add(run_id)
        sequence = trial.get("sequence")
        if type(sequence) is not int or sequence < 1 or sequence in seen_sequences:
            raise ScheduleError("trial_sequence_missing_or_duplicate")
        seen_sequences.add(sequence)
        if trial.get("model_id") != protocol["model_id"]:
            raise ScheduleError("trial_model_id_mismatch")
        if trial.get("task_id") != TASK_ID:
            raise ScheduleError("trial_task_id_mismatch")
        if trial.get("source_revision") != protocol["source_revision"]:
            raise ScheduleError("trial_source_revision_mismatch")
        if trial.get("pair_id") != f"pair-{(sequence + 1) // 2:04d}":
            raise ScheduleError("trial_pair_id_mismatch")
        if type(trial.get("attempt")) is not int or trial["attempt"] != 1:
            raise ScheduleError("trial_attempt_invalid")
        if trial.get("budgets") != protocol.get("budgets"):
            raise ScheduleError("trial_budget_mismatch")
        if trial.get("source_sha256") != protocol.get("source_sha256"):
            raise ScheduleError("trial_source_hash_mismatch")
        if trial.get("fresh_state_required") is not True:
            raise ScheduleError("trial_fresh_state_required")
        if trial.get("agent_visible_treatment_label") is not False:
            raise ScheduleError("trial_arm_label_must_be_hidden")
        by_pair.setdefault(trial["pair_id"], []).append(trial)

    if seen_sequences != set(range(1, len(trials) + 1)):
        raise ScheduleError("trial_sequences_must_be_contiguous")
    for pair_number in range(1, pairs + 1):
        pair_id = f"pair-{pair_number:04d}"
        items = by_pair.get(pair_id, [])
        if len(items) != 2 or {item["candidate_id"] for item in items} != set(ARMS):
            raise ScheduleError(f"pair_not_balanced:{pair_id}")
        if items[1]["sequence"] != items[0]["sequence"] + 1:
            raise ScheduleError(f"pair_trials_must_be_adjacent:{pair_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--max-input-tokens", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--max-tool-calls", type=int, required=True)
    parser.add_argument("--max-wall-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    schedule = create_schedule(
        pairs=args.pairs,
        seed=args.seed,
        model_id=args.model_id,
        source_revision=args.source_revision,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        max_tool_calls=args.max_tool_calls,
        max_wall_seconds=args.max_wall_seconds,
    )
    validate_schedule(schedule)
    output = args.output.expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(schedule, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    # Do not overwrite an existing schedule: it is an immutable experiment record.
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


if __name__ == "__main__":
    main()
