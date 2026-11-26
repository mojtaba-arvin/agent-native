"""Experimental trusted materializer for narrowly-scoped E-007 change proposals.

This module is not wired into the public Agent Gateway. It proves the delta
normalization and preservation boundary independently before any agent run.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
E009_ROOT = ROOT / "experiments" / "e009"
sys.path.insert(0, str(E009_ROOT))
from kernel import validate_ir  # noqa: E402

MAX_DELTA_BYTES = 64 * 1024
DELTA_FIELDS = {"service_id", "base_revision", "changes"}
CHANGE_FIELDS = {"kind", "operation"}
OPERATION_FIELDS = {
    "name", "method", "path", "input", "output",
    "errors", "validation", "effects", "capability",
}


class DeltaMaterializationError(ValueError):
    """A typed, fail-closed rejection of an experimental change intent."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DeltaMaterializationError("non_canonical_json_value") from error


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DeltaMaterializationError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise DeltaMaterializationError("non_finite_json_number")


def parse_delta_request(raw: bytes | str) -> dict:
    if isinstance(raw, bytes):
        if len(raw) > MAX_DELTA_BYTES:
            raise DeltaMaterializationError("delta_payload_too_large")
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DeltaMaterializationError("invalid_utf8") from error
    elif not isinstance(raw, str):
        raise DeltaMaterializationError("delta_payload_must_be_utf8_json")
    if len(raw.encode("utf-8")) > MAX_DELTA_BYTES:
        raise DeltaMaterializationError("delta_payload_too_large")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except DeltaMaterializationError:
        raise
    except json.JSONDecodeError as error:
        raise DeltaMaterializationError("invalid_json") from error
    if not isinstance(value, dict):
        raise DeltaMaterializationError("delta_request_must_be_object")
    return value


def _require_exact_fields(value: dict, expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise DeltaMaterializationError(code)


def _require_nonempty_string(value: Any, code: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DeltaMaterializationError(code)


def _validate_operation_shape(operation: Any) -> dict:
    if not isinstance(operation, dict):
        raise DeltaMaterializationError("operation_must_be_object")
    _require_exact_fields(operation, OPERATION_FIELDS, "operation_fields_invalid")
    for field in ("name", "method", "path", "output", "capability"):
        _require_nonempty_string(operation.get(field), f"operation_{field}_invalid")
    for field in ("errors", "validation", "effects"):
        value = operation.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise DeltaMaterializationError(f"operation_{field}_invalid")
    inputs = operation.get("input")
    if not isinstance(inputs, list):
        raise DeltaMaterializationError("operation_input_must_be_array")
    for declaration in inputs:
        if not isinstance(declaration, dict):
            raise DeltaMaterializationError("input_declaration_must_be_object")
        _require_exact_fields(declaration, {"name", "source", "type"}, "input_declaration_fields_invalid")
        for field in ("name", "source", "type"):
            _require_nonempty_string(declaration.get(field), f"input_declaration_{field}_invalid")
    return deepcopy(operation)


def materialize_add_operation(
    raw_request: bytes | str,
    *,
    service_id: str,
    current_service: dict,
    trusted_effects: set[str],
    trusted_capabilities: set[str],
) -> dict:
    """Materialize exactly one add_operation against the current trusted base.

    The change-set hash intentionally matches the snapshot proposal identity:
    SHA-256(service_id, exact base_revision, complete canonical resulting IR).
    For this single-operation append-only contract, the normalized intent is
    uniquely derivable from the base/result difference; its separate digest is
    returned for audit metadata.
    """
    _require_nonempty_string(service_id, "service_id_invalid")
    if not isinstance(current_service, dict):
        raise DeltaMaterializationError("trusted_base_must_be_object")

    request = parse_delta_request(raw_request)
    _require_exact_fields(request, DELTA_FIELDS, "delta_request_fields_invalid")
    if request.get("service_id") != service_id:
        raise DeltaMaterializationError("service_id_mismatch")

    base_revision = request.get("base_revision")
    if not isinstance(base_revision, str) or not re.fullmatch(r"[0-9a-f]{64}", base_revision):
        raise DeltaMaterializationError("base_revision_invalid")
    trusted_revision = digest(current_service)
    if base_revision != trusted_revision:
        raise DeltaMaterializationError("stale_base_revision")

    changes = request.get("changes")
    if not isinstance(changes, list) or len(changes) != 1:
        raise DeltaMaterializationError("exactly_one_change_required")
    change = changes[0]
    if not isinstance(change, dict):
        raise DeltaMaterializationError("change_must_be_object")
    _require_exact_fields(change, CHANGE_FIELDS, "change_fields_invalid")
    if change.get("kind") != "add_operation":
        raise DeltaMaterializationError("unsupported_change_kind")

    operation = _validate_operation_shape(change.get("operation"))
    existing_names = [item.get("name") for item in current_service.get("operations", [])]
    if operation["name"] in existing_names:
        raise DeltaMaterializationError("duplicate_operation_name")
    if not set(operation["effects"]).issubset(trusted_effects):
        raise DeltaMaterializationError("untrusted_effect")
    if operation["capability"] not in trusted_capabilities:
        raise DeltaMaterializationError("untrusted_capability")

    materialized = deepcopy(current_service)
    materialized["operations"].append(operation)
    try:
        validate_ir(materialized)
    except Exception as error:
        raise DeltaMaterializationError("materialized_ir_invalid") from error

    if (
        materialized.get("ir_version") != current_service.get("ir_version")
        or materialized.get("service") != current_service.get("service")
        or materialized.get("types") != current_service.get("types")
        or materialized.get("operations", [])[:-1] != current_service.get("operations")
        or len(materialized.get("operations", [])) != len(current_service.get("operations", [])) + 1
        or materialized["operations"][-1] != operation
    ):
        raise DeltaMaterializationError("materialized_base_preservation_failed")

    normalized_intent = {
        "service_id": service_id,
        "base_revision": base_revision,
        "changes": [{"kind": "add_operation", "operation": operation}],
    }
    proposal = {
        "service_id": service_id,
        "base_revision": base_revision,
        "ir": materialized,
    }
    return {
        **proposal,
        "change_set_id": digest(proposal),
        "intent_digest": digest(normalized_intent),
        "normalized_intent": normalized_intent,
        "materialized_ir_digest": digest(materialized),
    }
