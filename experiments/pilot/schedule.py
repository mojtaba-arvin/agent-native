"""Create deterministic, randomized paired trial schedules for the pilot.

The schedule is runner-only metadata. Never pass it to the agent. In particular,
candidate_id and disclosure_arm are treatment labels, not agent context.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import re
import subprocess
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parent
ROOT = PILOT_ROOT.parents[1]
TASK_ID = "pilot-catalog-add-readonly-operation"
ARMS = ("progressive", "upfront")
SOURCE_FILES = (
    ".gitignore",
    "experiments/pilot/README.md",
    "experiments/pilot/AGENT_ADAPTER.md",
    "experiments/pilot/ORACLE_CONTRACT.md",
    "experiments/pilot/PROMPT.md",
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
    "experiments/pilot/schedule.py",
    "experiments/pilot/verify_schedule.py",
    "experiments/e007/trace.schema.json",
    "experiments/e007/metrics.py",
)
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MAX_GENERATION_SETTINGS_BYTES = 1024 * 1024


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


def validate_generation_settings(value: Any) -> None:
    if not isinstance(value, dict):
        raise ScheduleError("generation_settings_must_be_object")
    try:
        canonical_json(value)
    except (TypeError, ValueError) as error:
        raise ScheduleError("generation_settings_must_be_finite_json") from error

    def reject_secret_keys(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ScheduleError("generation_setting_key_must_be_string")
                normalized = key.lower().replace("-", "_")
                if any(marker in normalized for marker in (
                    "api_key", "api_token", "access_token", "refresh_token",
                    "secret", "password", "credential", "authorization", "bearer",
                )):
                    raise ScheduleError("generation_settings_must_not_contain_credentials")
                reject_secret_keys(child)
        elif isinstance(item, list):
            for child in item:
                reject_secret_keys(child)

    reject_secret_keys(value)



def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ScheduleError("generation_settings_duplicate_json_key")
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> None:
    raise ScheduleError("generation_settings_non_finite_json_number")


def load_generation_settings(path: str | Path) -> dict:
    settings_path = Path(path).expanduser()
    try:
        if settings_path.stat().st_size > MAX_GENERATION_SETTINGS_BYTES:
            raise ScheduleError("generation_settings_file_too_large")
        raw = settings_path.read_bytes()
    except ScheduleError:
        raise
    except OSError as error:
        raise ScheduleError("generation_settings_file_unavailable") from error
    if len(raw) > MAX_GENERATION_SETTINGS_BYTES:
        raise ScheduleError("generation_settings_file_too_large")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_non_finite_json_number,
        )
    except UnicodeDecodeError as error:
        raise ScheduleError("generation_settings_invalid_utf8") from error
    except json.JSONDecodeError as error:
        raise ScheduleError("generation_settings_invalid_json") from error
    validate_generation_settings(value)
    return value


def resolve_output_outside_checkout(path: str | Path, root: str | Path = ROOT) -> Path:
    output = Path(path).expanduser().resolve()
    checkout = Path(root).resolve()
    try:
        output.relative_to(checkout)
    except ValueError:
        return output
    raise ScheduleError("schedule_output_must_be_outside_checkout")


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



def resolve_git_revision(root: str | Path = ROOT) -> str:
    """Resolve the actual HEAD and refuse to pin a dirty working tree."""
    base = Path(root).resolve()
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=base,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ScheduleError("git_revision_unavailable") from error
    if not REVISION_PATTERN.fullmatch(revision):
        raise ScheduleError("git_revision_invalid")
    if status.strip():
        raise ScheduleError("working_tree_must_be_clean_before_scheduling")
    return revision


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
    generation_settings: dict,
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

    validate_generation_settings(generation_settings)
    source_hashes = hash_source_files(root)
    protocol = {
        "protocol_version": 1,
        "task_id": TASK_ID,
        "source_revision": source_revision,
        "source_sha256": source_hashes,
        "model_id": model_id.strip(),
        "generation_settings": generation_settings,
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
                "generation_settings": copy.deepcopy(protocol["generation_settings"]),
                "task_id": TASK_ID,
                "attempt": 1,
                "source_revision": source_revision,
                "source_sha256": copy.deepcopy(source_hashes),
                "budgets": copy.deepcopy(budgets),
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
        "model_id", "generation_settings", "budgets", "pairs", "seed", "arms", "randomization",
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
    try:
        validate_generation_settings(protocol.get("generation_settings"))
    except ScheduleError as error:
        raise ScheduleError("protocol_generation_settings_invalid") from error
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
        "generation_settings", "task_id", "attempt", "source_revision", "source_sha256",
        "budgets", "fresh_state_required", "agent_visible_treatment_label",
    }
    for expected_sequence, trial in enumerate(trials, 1):
        if not isinstance(trial, dict) or set(trial) != trial_fields:
            raise ScheduleError("trial_shape_invalid")
        if trial.get("candidate_id") not in ARMS:
            raise ScheduleError("trial_candidate_invalid")
        run_id = trial.get("run_id")
        if not isinstance(run_id, str) or run_id in seen_run_ids:
            raise ScheduleError("trial_run_id_missing_or_duplicate")
        seen_run_ids.add(run_id)
        sequence = trial.get("sequence")
        if type(sequence) is not int or sequence != expected_sequence or sequence in seen_sequences:
            raise ScheduleError("trial_sequence_missing_or_duplicate")
        seen_sequences.add(sequence)
        if trial.get("model_id") != protocol["model_id"]:
            raise ScheduleError("trial_model_id_mismatch")
        if trial.get("generation_settings") != protocol["generation_settings"]:
            raise ScheduleError("trial_generation_settings_mismatch")
        if trial.get("task_id") != TASK_ID:
            raise ScheduleError("trial_task_id_mismatch")
        if trial.get("source_revision") != protocol["source_revision"]:
            raise ScheduleError("trial_source_revision_mismatch")
        pair_number = (sequence + 1) // 2
        if trial.get("pair_id") != f"pair-{pair_number:04d}":
            raise ScheduleError("trial_pair_id_mismatch")
        expected_run_hash = sha256_bytes(
            f"{schedule['plan_id']}:{pair_number}:{trial['candidate_id']}".encode("utf-8")
        )
        expected_run_id = f"pair-{pair_number:04d}-{trial['candidate_id']}-{expected_run_hash[:12]}"
        if run_id != expected_run_id:
            raise ScheduleError("trial_run_id_mismatch")
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



def verify_schedule_checkout(
    schedule: Any,
    *,
    root: str | Path = ROOT,
) -> None:
    """Verify a schedule was created from this exact clean source checkout."""
    validate_schedule(schedule)
    actual_revision = resolve_git_revision(root)
    expected_revision = schedule["protocol"]["source_revision"]
    if actual_revision != expected_revision:
        raise ScheduleError("checkout_revision_does_not_match_schedule")
    actual_hashes = hash_source_files(root)
    expected_hashes = schedule["protocol"]["source_sha256"]
    if actual_hashes != expected_hashes:
        mismatches = sorted(
            path for path in set(actual_hashes) | set(expected_hashes)
            if actual_hashes.get(path) != expected_hashes.get(path)
        )
        raise ScheduleError(f"checkout_source_hash_mismatch:{','.join(mismatches)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--generation-settings-file", required=True, type=Path)
    parser.add_argument("--max-input-tokens", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--max-tool-calls", type=int, required=True)
    parser.add_argument("--max-wall-seconds", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        settings_file = resolve_output_outside_checkout(args.generation_settings_file)
        generation_settings = load_generation_settings(settings_file)
        output = resolve_output_outside_checkout(args.output)
    except ScheduleError as error:
        parser.error(str(error))

    schedule = create_schedule(
        pairs=args.pairs,
        seed=args.seed,
        model_id=args.model_id,
        source_revision=resolve_git_revision(ROOT),
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        max_tool_calls=args.max_tool_calls,
        max_wall_seconds=args.max_wall_seconds,
        generation_settings=generation_settings,
    )
    validate_schedule(schedule)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(schedule, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    # Do not overwrite an existing schedule: it is an immutable experiment record.
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


if __name__ == "__main__":
    main()
