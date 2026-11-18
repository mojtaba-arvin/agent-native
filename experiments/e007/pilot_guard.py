#!/usr/bin/env python3
"""Fail-fast policy for infrastructure-invalid E-007 matched cohorts."""

from __future__ import annotations

import json
from pathlib import Path


ABORT_CATEGORIES = {
    "transport_error",
    "provider_http_error",
    "model_configuration_or_adapter",
    "runner_or_gateway_error",
    "resource_exhaustion",
}


def cohort_abort_reason(result_path: str | Path) -> str | None:
    """Return a reason to stop before the next cell; fail closed on missing evidence.

    Agent/task failures remain in the cohort so the other matched cells can still
    be compared. Shared provider/runner faults invalidate the cohort and should
    not consume the remaining model budget.
    """
    path = Path(result_path)
    if not path.is_file():
        return "result_artifact_missing"

    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "result_artifact_unreadable"

    if not isinstance(result, dict):
        return "result_artifact_invalid"
    categories = result.get("failure_categories")
    if not isinstance(categories, dict):
        return "failure_categories_missing"
    if any(not isinstance(key, str) for key in categories):
        return "failure_categories_invalid"

    observed = sorted(ABORT_CATEGORIES.intersection(
        key for key, count in categories.items()
        if isinstance(count, int) and not isinstance(count, bool) and count > 0
    ))
    if observed:
        return "shared_infrastructure_failure:" + ",".join(observed)
    return None
