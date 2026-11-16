"""Load and validate the machine-readable Agent Native service contract."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MANIFEST_NAME = "agent-native.json"
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_ALLOWED_ROOT = {"schema_version", "name", "version", "entrypoint", "operations"}
_ALLOWED_OPERATION = {"id", "method", "path", "summary"}
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class ManifestError(ValueError):
    """Raised when a service manifest is invalid."""


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"Missing {MANIFEST_NAME} in {root}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Cannot read {MANIFEST_NAME}: {exc}") from exc
    validate_manifest(data)
    return data


def validate_manifest(data: Any) -> None:
    if not isinstance(data, dict):
        raise ManifestError("Manifest root must be a JSON object")
    unknown = set(data) - _ALLOWED_ROOT
    missing = _ALLOWED_ROOT - set(data)
    if unknown:
        raise ManifestError(f"Unknown manifest keys: {', '.join(sorted(unknown))}")
    if missing:
        raise ManifestError(f"Missing manifest keys: {', '.join(sorted(missing))}")
    if data["schema_version"] != "1":
        raise ManifestError("schema_version must be the string '1'")
    if not isinstance(data["name"], str) or not _NAME.fullmatch(data["name"]):
        raise ManifestError("name must be 2-63 lowercase letters, digits, or hyphens and start with a letter")
    if not isinstance(data["version"], str) or not re.fullmatch(r"(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)", data["version"]):
        raise ManifestError("version must be a semantic version (for example 0.1.0)")
    entrypoint = data["entrypoint"]
    if not isinstance(entrypoint, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*:[a-zA-Z_][a-zA-Z0-9_]*", entrypoint):
        raise ManifestError("entrypoint must use module:attribute syntax")
    operations = data["operations"]
    if not isinstance(operations, list):
        raise ManifestError("operations must be an array")
    seen_ids: set[str] = set()
    seen_routes: set[tuple[str, str]] = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ManifestError(f"operations[{index}] must be an object")
        unknown_operation = set(operation) - _ALLOWED_OPERATION
        missing_operation = _ALLOWED_OPERATION - set(operation)
        if unknown_operation or missing_operation:
            raise ManifestError(f"operations[{index}] keys invalid; missing={sorted(missing_operation)}, unknown={sorted(unknown_operation)}")
        op_id, method, route, summary = (operation[k] for k in ("id", "method", "path", "summary"))
        if not isinstance(op_id, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", op_id):
            raise ManifestError(f"operations[{index}].id is invalid")
        if op_id in seen_ids:
            raise ManifestError(f"Duplicate operation id: {op_id}")
        if method not in _METHODS:
            raise ManifestError(f"operations[{index}].method must be one of {sorted(_METHODS)}")
        if not isinstance(route, str) or not route.startswith("/") or "{" in route or "}" in route or "//" in route:
            raise ManifestError(f"operations[{index}].path must be a static absolute path")
        if (method, route) in seen_routes:
            raise ManifestError(f"Duplicate route: {method} {route}")
        if not isinstance(summary, str) or not summary.strip():
            raise ManifestError(f"operations[{index}].summary must be a non-empty string")
        seen_ids.add(op_id)
        seen_routes.add((method, route))
