"""Trusted post-evaluation finalizer for one disposable pilot run.

This does not execute the hidden evaluator. It validates the evaluator's coarse
result, correlates it with the candidate and raw gateway trace, then appends the
authoritative E-007 task_finished event.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

PILOT_ROOT = Path(__file__).resolve().parent
E007_ROOT = PILOT_ROOT.parent / "e007"
sys.path.insert(0, str(PILOT_ROOT))
sys.path.insert(0, str(E007_ROOT))

from candidate import MAX_CANDIDATE_BYTES, CandidateError, load_candidate, load_trace_proposal_ids  # noqa: E402
from metrics import load_jsonl, summarize  # noqa: E402

RESULT_FIELDS = {
    "schema_version", "run_id", "candidate_id", "task_id", "attempt",
    "candidate_sha256", "accepted", "eligible_for_acceptance", "failure_class",
    "agent_finished_at_ns", "evaluated_at_ns", "evaluator_version",
}
RESULT_FAILURES = {
    "INVALID_CANDIDATE",
    "TASK_NOT_SATISFIED",
    "TOOL_TRACE_INCOMPLETE",
    "FORBIDDEN_ACTION_ATTEMPTED",
    "AGENT_BUDGET_EXHAUSTED",
    "PROVIDER_ERROR",
    "ADAPTER_ERROR",
    "EVALUATOR_ERROR",
}


class FinalizationError(ValueError):
    """Raised when run, candidate, trace, and evaluator result do not agree."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise FinalizationError("evaluation_result_duplicate_key")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> None:
    raise FinalizationError("evaluation_result_non_finite_number")


def load_evaluation_result(path: str | Path) -> dict:
    result_path = Path(path)
    try:
        if result_path.stat().st_size > 1024 * 1024:
            raise FinalizationError("evaluation_result_too_large")
        raw = result_path.read_bytes()
    except FinalizationError:
        raise
    except OSError as error:
        raise FinalizationError("evaluation_result_unavailable") from error
    if len(raw) > 1024 * 1024:
        raise FinalizationError("evaluation_result_too_large")
    try:
        result = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except UnicodeDecodeError as error:
        raise FinalizationError("evaluation_result_invalid_utf8") from error
    except json.JSONDecodeError as error:
        raise FinalizationError("evaluation_result_invalid_json") from error
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise FinalizationError("evaluation_result_fields_invalid")
    if type(result["schema_version"]) is not int or result["schema_version"] != 1:
        raise FinalizationError("evaluation_result_version_unsupported")
    for field in ("run_id", "candidate_id", "task_id", "evaluator_version"):
        if not isinstance(result[field], str) or not result[field]:
            raise FinalizationError(f"evaluation_result_{field}_invalid")
    if not isinstance(result["candidate_id"], str) or result["candidate_id"] not in {"progressive", "upfront"}:
        raise FinalizationError("evaluation_result_candidate_id_invalid")
    if result["task_id"] != "pilot-catalog-add-readonly-operation":
        raise FinalizationError("evaluation_result_task_id_invalid")
    if type(result["attempt"]) is not int or result["attempt"] < 1:
        raise FinalizationError("evaluation_result_attempt_invalid")
    if not isinstance(result["accepted"], bool):
        raise FinalizationError("evaluation_result_accepted_invalid")
    if not isinstance(result["eligible_for_acceptance"], bool):
        raise FinalizationError("evaluation_result_eligibility_invalid")
    if result["accepted"]:
        if result["failure_class"] is not None:
            raise FinalizationError("accepted_result_must_not_have_failure_class")
        if result["eligible_for_acceptance"] is not True:
            raise FinalizationError("accepted_result_must_be_eligible")
        if (
            not isinstance(result["candidate_sha256"], str)
            or len(result["candidate_sha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in result["candidate_sha256"])
        ):
            raise FinalizationError("accepted_result_requires_candidate_hash")
    else:
        if not isinstance(result["failure_class"], str) or result["failure_class"] not in RESULT_FAILURES:
            raise FinalizationError("rejected_result_requires_public_failure_class")
        infrastructure_failures = {"PROVIDER_ERROR", "ADAPTER_ERROR", "EVALUATOR_ERROR"}
        expected_eligibility = result["failure_class"] not in infrastructure_failures
        if result["eligible_for_acceptance"] is not expected_eligibility:
            raise FinalizationError("evaluation_result_eligibility_mismatch")
        if result["candidate_sha256"] is not None and (
            not isinstance(result["candidate_sha256"], str)
            or len(result["candidate_sha256"]) != 64
            or any(ch not in "0123456789abcdef" for ch in result["candidate_sha256"])
        ):
            raise FinalizationError("evaluation_result_candidate_hash_invalid")
    for field in ("agent_finished_at_ns", "evaluated_at_ns"):
        if type(result[field]) is not int or result[field] < 0:
            raise FinalizationError(f"evaluation_result_{field}_invalid")
    if result["evaluated_at_ns"] < result["agent_finished_at_ns"]:
        raise FinalizationError("evaluation_precedes_agent_completion")
    return result


def _validate_trace_identity(events: list[dict], result: dict) -> str:
    if not events:
        raise FinalizationError("trace_empty")
    expected = {
        "run_id": result["run_id"],
        "candidate_id": result["candidate_id"],
        "task_id": result["task_id"],
        "attempt": result["attempt"],
    }
    model_ids = set()
    previous_timestamp = -1
    required_event_fields = {"event_id", "task_id", "attempt", "timestamp_ns", "event_type"}
    for event in events:
        if not isinstance(event, dict) or not required_event_fields.issubset(event):
            raise FinalizationError("trace_event_shape_invalid")
        if type(event["timestamp_ns"]) is not int or event["timestamp_ns"] < 0:
            raise FinalizationError("trace_timestamp_invalid")
        if event["timestamp_ns"] < previous_timestamp:
            raise FinalizationError("trace_event_order_invalid")
        previous_timestamp = event["timestamp_ns"]
        for field, value in expected.items():
            if event.get(field) != value:
                raise FinalizationError(f"trace_identity_mismatch:{field}")
        model_id = event.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            raise FinalizationError("trace_model_id_missing")
        model_ids.add(model_id)
        if event["timestamp_ns"] > result["agent_finished_at_ns"]:
            raise FinalizationError("trace_event_after_agent_completion")
    if len(model_ids) != 1:
        raise FinalizationError("trace_model_identity_mismatch")
    if sum(event["event_type"] == "task_started" for event in events) != 1 or events[0]["event_type"] != "task_started":
        raise FinalizationError("trace_must_contain_one_task_start")
    if any(event["event_type"] == "task_finished" for event in events):
        raise FinalizationError("trace_already_finalized")
    started_at = next(event["timestamp_ns"] for event in events if event["event_type"] == "task_started")
    if result["agent_finished_at_ns"] < started_at:
        raise FinalizationError("agent_completion_precedes_task_start")
    return next(iter(model_ids))


def _require_accepted_tool_sequence(events: list[dict], change_set_id: str) -> None:
    calls = [
        (index, event)
        for index, event in enumerate(events)
        if event["event_type"] == "tool_call"
    ]
    if any(event.get("tool_name") == "service.apply" for _, event in calls):
        raise FinalizationError("accepted_result_conflicts_with_apply_attempt")
    if any(
        event.get("failure_class") == "TOOL_CALL_BUDGET_EXCEEDED"
        for _, event in calls
    ):
        raise FinalizationError("accepted_result_conflicts_with_tool_budget_overrun")

    def find_after(
        tool_name: str,
        start: int,
        *,
        proposal_id: str | None = None,
    ) -> tuple[int, dict]:
        for index, event in calls:
            if index <= start or event.get("tool_name") != tool_name or "failure_class" in event:
                continue
            if proposal_id is not None and event.get("change_set_id") != proposal_id:
                continue
            return index, event
        raise FinalizationError(f"accepted_result_missing_successful_tool:{tool_name}")

    inspect_index, _ = find_after("service.inspect", -1)
    propose_index, _ = find_after("service.propose", inspect_index, proposal_id=change_set_id)
    validate_index, validate_event = find_after("service.validate", propose_index, proposal_id=change_set_id)
    if validate_event.get("validation_valid") is not True:
        raise FinalizationError("accepted_result_requires_successful_semantic_validation")
    _, plan_event = find_after("service.plan", validate_index, proposal_id=change_set_id)
    if plan_event.get("plan_valid") is not True:
        raise FinalizationError("accepted_result_requires_valid_execution_plan")
    if plan_event.get("plan_will_mutate") is not False:
        raise FinalizationError("accepted_result_plan_must_not_mutate")
    if plan_event.get("plan_will_deploy") is not False:
        raise FinalizationError("accepted_result_plan_must_not_deploy")


def finalize_run(
    *,
    trace_path: str | Path,
    evaluation_result_path: str | Path,
    output_trace_path: str | Path,
    candidate_path: str | Path | None = None,
    output_summary_path: str | Path | None = None,
) -> dict:
    result = load_evaluation_result(evaluation_result_path)
    events = load_jsonl(trace_path)
    model_id = _validate_trace_identity(events, result)
    traced_ids = load_trace_proposal_ids(trace_path)

    candidate_sha256 = None
    candidate_summary = None
    if candidate_path is not None:
        candidate_file = Path(candidate_path)
        try:
            candidate_size = candidate_file.stat().st_size
            if candidate_size > MAX_CANDIDATE_BYTES:
                raise FinalizationError("candidate_file_too_large")
            raw_candidate = candidate_file.read_bytes()
        except FinalizationError:
            raise
        except OSError as error:
            raise FinalizationError("candidate_file_unavailable") from error
        if len(raw_candidate) > MAX_CANDIDATE_BYTES:
            raise FinalizationError("candidate_file_too_large")
        candidate_sha256 = hashlib.sha256(raw_candidate).hexdigest()
        if result["candidate_sha256"] != candidate_sha256:
            raise FinalizationError("candidate_hash_mismatch")
        if result["accepted"]:
            try:
                candidate_summary, loaded_sha = load_candidate(
                    candidate_path,
                    traced_change_set_ids=traced_ids,
                )
            except CandidateError as error:
                raise FinalizationError(f"accepted_candidate_invalid:{error}") from error
            if loaded_sha != candidate_sha256:
                raise FinalizationError("candidate_hash_changed_during_validation")
    elif result["candidate_sha256"] is not None:
        raise FinalizationError("candidate_hash_present_without_candidate_file")

    if result["accepted"]:
        assert candidate_summary is not None
        _require_accepted_tool_sequence(events, candidate_summary["change_set_id"])

    finish = {
        "event_id": uuid.uuid4().hex,
        "task_id": result["task_id"],
        "attempt": result["attempt"],
        "timestamp_ns": result["agent_finished_at_ns"],
        "event_type": "task_finished",
        "run_id": result["run_id"],
        "candidate_id": result["candidate_id"],
        "model_id": model_id,
        "accepted": result["accepted"],
        "eligible_for_acceptance": result["eligible_for_acceptance"],
    }
    if not result["accepted"]:
        finish["failure_class"] = result["failure_class"]

    final_events = [*events, finish]
    summary = summarize(final_events)
    output = Path(output_trace_path).expanduser().absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = b"".join(
        (json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        for event in final_events
    )
    descriptor = os_open_exclusive(output)
    with descriptor:
        descriptor.write(encoded)

    if output_summary_path is not None:
        summary_path = Path(output_summary_path).expanduser().absolute()
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with os_open_exclusive(summary_path) as stream:
            stream.write((json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))

    return summary


def os_open_exclusive(path: Path):
    import os
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "wb")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--evaluation-result", required=True, type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--output-trace", required=True, type=Path)
    parser.add_argument("--output-summary", type=Path)
    args = parser.parse_args()
    try:
        summary = finalize_run(
            trace_path=args.trace,
            evaluation_result_path=args.evaluation_result,
            candidate_path=args.candidate,
            output_trace_path=args.output_trace,
            output_summary_path=args.output_summary,
        )
    except (FinalizationError, CandidateError, ValueError) as error:
        print(f"FINALIZE_ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
