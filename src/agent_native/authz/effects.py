"""Explicit mapping from service effects to gateway access modes."""

from __future__ import annotations

from types import MappingProxyType
from typing import Iterable


EFFECT_ACCESS_MODE = MappingProxyType({
    "repository.read": "read",
    "queue.read": "read",
    "repository.write": "write",
    "queue.submit": "write",
    "queue.cancel": "write",
    "event.publish": "write",
})


def classify_effects(effects: Iterable[str]) -> str:
    """Classify declared effects; unknown effects fail closed."""
    try:
        selected = frozenset(effects)
    except TypeError as error:
        raise ValueError("effects must be an iterable of effect IDs") from error
    if not selected or any(not isinstance(effect, str) or not effect for effect in selected):
        raise ValueError("at least one valid effect is required")
    unsupported = selected - set(EFFECT_ACCESS_MODE)
    if unsupported:
        raise ValueError(f"unsupported effects: {', '.join(sorted(unsupported))}")
    return "write" if "write" in {EFFECT_ACCESS_MODE[item] for item in selected} else "read"
