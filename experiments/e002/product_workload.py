"""Deterministic request classes for the E-002 product workload."""

from __future__ import annotations

import random
from collections import Counter

WORKLOAD_SEED = 20261122
_REQUEST_BLOCK = (
    ["authorized_read"] * 6
    + ["validate_plan"] * 2
    + ["job_admission"]
    + ["expected_denial"]
)


def _validate_seed(seed: int) -> None:
    if type(seed) is not int:
        raise TypeError("workload_seed_must_be_integer")


def request_class(index: int, *, seed: int = WORKLOAD_SEED) -> str:
    """Return a reproducible randomized class with exact 60/20/10/10 blocks.

    Negative indices are rejected rather than silently addressing a schedule
    block before the beginning of the workload. Booleans are rejected as
    indices/seeds even though ``bool`` subclasses ``int`` in Python.
    """
    if type(index) is not int:
        raise TypeError("request_index_must_be_integer")
    if index < 0:
        raise ValueError("request_index_must_be_non_negative")
    _validate_seed(seed)
    block, offset = divmod(index, len(_REQUEST_BLOCK))
    schedule = list(_REQUEST_BLOCK)
    random.Random(f"{seed}:{block}").shuffle(schedule)
    return schedule[offset]


def mix_counts(requests: int, *, seed: int = WORKLOAD_SEED) -> dict[str, int]:
    if type(requests) is not int:
        raise TypeError("requests_must_be_integer")
    if requests < 0:
        raise ValueError("requests_must_be_non_negative")
    _validate_seed(seed)
    return dict(sorted(Counter(
        request_class(index, seed=seed) for index in range(requests)
    ).items()))
