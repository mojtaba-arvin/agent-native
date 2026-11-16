"""Strict public-envelope checks for the pilot's untrusted candidate artifact.

This validates artifact shape and content-addressing only. It is not the
acceptance oracle and does not decide whether the requested change is correct.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

TASK_ID = "pilot-catalog-add-readonly-operation"
SERVICE_ID = "catalog"
MAX_CANDIDATE_BYTES = 1024 * 1024
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TOP_LEVEL_FIELDS = {
    "schema_version", "task_id", "service_id",
    "base_revision", "change_set_id", "ir",
}
IR_FIELDS = {"ir_version", "service", "types", "operations"}
OPERATION_FIELDS = {
    "name", "method", "path", "input", "output",
    "errors", "validation", "effects", "capability",
}


class CandidateError(ValueError):
    """Raised when an untrusted candidate does not match the public envelope."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise CandidateError("duplicate_json_key")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> None:
    raise CandidateError("non_finite_json_number")


def canonical_digest(value: dict) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CandidateError("candidate_is_not_finite_json") from error
    return hashlib.sha256(encoded).hexdigest()


def _require_object(value: Any, fields: set[str], code: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise CandidateError(code)
    return value


def validate_candidate(
    candidate: Any,
    *,
    traced_change_set_ids: set[str] | None = None,
) -> dict:
    artifact = _require_object(candidate, TOP_LEVEL_FIELDS, "candidate_fields_invalid")
    if type(artifact["schema_version"]) is not int or artifact["schema_version"] != 1:
        raise CandidateError("candidate_schema_version_unsupported")
    if artifact["task_id"] != TASK_ID or artifact["service_id"] != SERVICE_ID:
        raise CandidateError("candidate_task_or_service_mismatch")
    for field in ("base_revision", "change_set_id"):
        if not isinstance(artifact[field], str) or not SHA256_PATTERN.fullmatch(artifact[field]):
            raise CandidateError(f"candidate_{field}_invalid")

    ir = _require_object(artifact["ir"], IR_FIELDS, "candidate_ir_shape_invalid")
    if type(ir["ir_version"]) is not int or ir["ir_version"] != 1:
        raise CandidateError("candidate_ir_version_unsupported")

    service = _require_object(
        ir["service"],
        {"name", "version"},
        "candidate_service_shape_invalid",
    )
    if service != {"name": "Catalog", "version": "1"}:
        raise CandidateError("candidate_service_identity_invalid")

    if not isinstance(ir["types"], list) or not isinstance(ir["operations"], list) or not ir["operations"]:
        raise CandidateError("candidate_ir_collections_invalid")
    for item_type in ir["types"]:
        item_type = _require_object(
            item_type,
            {"name", "fields"},
            "candidate_type_shape_invalid",
        )
        if not isinstance(item_type["name"], str) or not item_type["name"] or not isinstance(item_type["fields"], list) or not item_type["fields"]:
            raise CandidateError("candidate_type_value_invalid")
        for field in item_type["fields"]:
            field = _require_object(field, {"name", "type"}, "candidate_type_field_shape_invalid")
            if not all(isinstance(field[key], str) and field[key] for key in ("name", "type")):
                raise CandidateError("candidate_type_field_value_invalid")
            if not IDENTIFIER_PATTERN.fullmatch(field["name"]):
                raise CandidateError("candidate_type_field_name_invalid")

    for operation in ir["operations"]:
        operation = _require_object(operation, OPERATION_FIELDS, "candidate_operation_shape_invalid")
        for key in ("name", "method", "path", "output", "capability"):
            if not isinstance(operation[key], str) or not operation[key]:
                raise CandidateError(f"candidate_operation_{key}_invalid")
        if not IDENTIFIER_PATTERN.fullmatch(operation["name"]):
            raise CandidateError("candidate_operation_name_invalid")
        if operation["method"] not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise CandidateError("candidate_operation_method_invalid")
        if not isinstance(operation["input"], list):
            raise CandidateError("candidate_operation_input_invalid")
        for field in operation["input"]:
            field = _require_object(field, {"name", "type", "source"}, "candidate_input_shape_invalid")
            if not all(isinstance(field[key], str) and field[key] for key in ("name", "type", "source")):
                raise CandidateError("candidate_input_value_invalid")
            if not IDENTIFIER_PATTERN.fullmatch(field["name"]):
                raise CandidateError("candidate_input_name_invalid")
            if field["source"] not in {"path", "query", "body", "header"}:
                raise CandidateError("candidate_input_source_invalid")
        for key in ("errors", "validation", "effects"):
            if not isinstance(operation[key], list) or any(
                not isinstance(value, str) or not value for value in operation[key]
            ):
                raise CandidateError(f"candidate_operation_{key}_invalid")

    proposal = {
        "service_id": artifact["service_id"],
        "base_revision": artifact["base_revision"],
        "ir": artifact["ir"],
    }
    computed_id = canonical_digest(proposal)
    if computed_id != artifact["change_set_id"]:
        raise CandidateError("candidate_change_set_id_mismatch")
    if traced_change_set_ids is not None and computed_id not in traced_change_set_ids:
        raise CandidateError("candidate_proposal_not_present_in_trace")

    return {
        "task_id": artifact["task_id"],
        "service_id": artifact["service_id"],
        "base_revision": artifact["base_revision"],
        "change_set_id": computed_id,
        "operation_count": len(ir["operations"]),
    }



def load_trace_proposal_ids(path: str | Path) -> set[str]:
    """Read proposal IDs emitted by successful service.propose calls only."""
    trace_path = Path(path)
    try:
        if trace_path.stat().st_size > 64 * 1024 * 1024:
            raise CandidateError("trace_file_too_large")
        raw = trace_path.read_bytes()
    except CandidateError:
        raise
    except OSError as error:
        raise CandidateError("trace_file_unavailable") from error
    if len(raw) > 64 * 1024 * 1024:
        raise CandidateError("trace_file_too_large")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CandidateError("trace_invalid_utf8") from error

    proposal_ids: set[str] = set()
    for line_number, line in enumerate(decoded.splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite,
            )
        except (json.JSONDecodeError, CandidateError) as error:
            raise CandidateError(f"trace_invalid_jsonl_line:{line_number}") from error
        if not isinstance(event, dict):
            raise CandidateError(f"trace_event_not_object:{line_number}")
        if event.get("event_type") == "tool_call" and event.get("tool_name") == "service.propose":
            if event.get("failure_class"):
                continue
            change_set_id = event.get("change_set_id")
            if not isinstance(change_set_id, str) or not SHA256_PATTERN.fullmatch(change_set_id):
                raise CandidateError(f"trace_successful_proposal_missing_hash:{line_number}")
            proposal_ids.add(change_set_id)
    return proposal_ids

def load_candidate(
    path: str | Path,
    *,
    traced_change_set_ids: set[str] | None = None,
) -> tuple[dict, str]:
    candidate_path = Path(path)
    try:
        if candidate_path.stat().st_size > MAX_CANDIDATE_BYTES:
            raise CandidateError("candidate_file_too_large")
        raw = candidate_path.read_bytes()
    except CandidateError:
        raise
    except OSError as error:
        raise CandidateError("candidate_file_unavailable") from error
    if len(raw) > MAX_CANDIDATE_BYTES:
        raise CandidateError("candidate_file_too_large")
    try:
        candidate = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except UnicodeDecodeError as error:
        raise CandidateError("candidate_invalid_utf8") from error
    except json.JSONDecodeError as error:
        raise CandidateError("candidate_invalid_json") from error
    summary = validate_candidate(
        candidate,
        traced_change_set_ids=traced_change_set_ids,
    )
    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    return summary, artifact_sha256
