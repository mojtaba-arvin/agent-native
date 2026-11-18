"""Transport-neutral E-011 call semantics model; not a wire protocol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import copy
import hashlib
import json
from typing import Any


class CallState(str, Enum):
    CREATED = "created"
    REJECTED_BEFORE_DISPATCH = "rejected_before_dispatch"
    ACCEPTED = "accepted_or_in_progress"
    COMPLETED = "completed"
    FAILED_BEFORE_EFFECT = "failed_before_effect"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED_AND_STOPPED = "cancelled_and_stopped"
    OUTCOME_UNKNOWN = "outcome_unknown_after_dispatch"


class InvalidTransition(ValueError):
    pass


_ALLOWED: dict[CallState, frozenset[CallState]] = {
    CallState.CREATED: frozenset({
        CallState.REJECTED_BEFORE_DISPATCH,
        CallState.ACCEPTED,
        CallState.FAILED_BEFORE_EFFECT,
        CallState.OUTCOME_UNKNOWN,
    }),
    CallState.ACCEPTED: frozenset({
        CallState.COMPLETED,
        CallState.FAILED_BEFORE_EFFECT,
        CallState.CANCEL_REQUESTED,
        CallState.OUTCOME_UNKNOWN,
    }),
    CallState.CANCEL_REQUESTED: frozenset({
        CallState.CANCELLED_AND_STOPPED,
        CallState.COMPLETED,
        CallState.OUTCOME_UNKNOWN,
    }),
    CallState.OUTCOME_UNKNOWN: frozenset({
        CallState.ACCEPTED,
        CallState.COMPLETED,
        CallState.FAILED_BEFORE_EFFECT,
        CallState.CANCEL_REQUESTED,
        CallState.CANCELLED_AND_STOPPED,
    }),
    CallState.REJECTED_BEFORE_DISPATCH: frozenset(),
    CallState.COMPLETED: frozenset(),
    CallState.FAILED_BEFORE_EFFECT: frozenset(),
    CallState.CANCELLED_AND_STOPPED: frozenset(),
}


@dataclass
class CallLifecycle:
    state: CallState = CallState.CREATED
    history: tuple[CallState, ...] = (CallState.CREATED,)

    def transition(self, next_state: CallState) -> None:
        if next_state not in _ALLOWED[self.state]:
            raise InvalidTransition(f"{self.state.value}->{next_state.value}")
        self.state = next_state
        self.history = (*self.history, next_state)


def retry_action(state: CallState, *, operation_retryable: bool) -> str:
    """Return a safe caller action; never infer non-execution from a timeout."""
    if state in {CallState.ACCEPTED, CallState.OUTCOME_UNKNOWN, CallState.CANCEL_REQUESTED}:
        return "reconcile_same_key"
    if state == CallState.COMPLETED:
        return "return_recorded_outcome"
    if state == CallState.REJECTED_BEFORE_DISPATCH:
        return "retry_new_attempt" if operation_retryable else "stop"
    if state == CallState.CANCELLED_AND_STOPPED:
        return "return_recorded_outcome"
    if state == CallState.FAILED_BEFORE_EFFECT:
        return "retry_same_key" if operation_retryable else "stop"
    return "do_not_retry"


@dataclass(frozen=True)
class DeadlineBudget:
    remaining_ms: int

    def __post_init__(self) -> None:
        if type(self.remaining_ms) is not int or self.remaining_ms < 0:
            raise ValueError("invalid_remaining_ms")

    @classmethod
    def receive(cls, advertised_remaining_ms: int, *, local_cap_ms: int) -> "DeadlineBudget":
        if type(advertised_remaining_ms) is not int or advertised_remaining_ms < 0:
            raise ValueError("invalid_advertised_deadline")
        if type(local_cap_ms) is not int or local_cap_ms < 0:
            raise ValueError("invalid_local_deadline_cap")
        return cls(min(advertised_remaining_ms, local_cap_ms))

    def after_elapsed(self, elapsed_ms: int) -> "DeadlineBudget":
        if type(elapsed_ms) is not int or elapsed_ms < 0:
            raise ValueError("invalid_elapsed_ms")
        return DeadlineBudget(max(0, self.remaining_ms - elapsed_ms))


@dataclass(frozen=True)
class Capability:
    issuer: str
    subject: str
    audience: str
    tenant: str
    operations: frozenset[str]
    resources: frozenset[str]
    expires_at: int
    delegable_audiences: frozenset[str] = frozenset()

    def attenuate(
        self,
        *,
        audience: str,
        operations: frozenset[str],
        resources: frozenset[str],
        expires_at: int,
    ) -> "Capability":
        if audience == "":
            raise ValueError("empty_audience")
        if audience not in self.delegable_audiences:
            raise ValueError("capability_audience_escalation")
        if not operations.issubset(self.operations):
            raise ValueError("capability_operation_escalation")
        if not resources.issubset(self.resources):
            raise ValueError("capability_resource_escalation")
        if type(expires_at) is not int or expires_at > self.expires_at:
            raise ValueError("capability_expiry_escalation")
        return Capability(
            issuer=self.issuer,
            subject=self.subject,
            audience=audience,
            tenant=self.tenant,
            operations=operations,
            resources=resources,
            expires_at=expires_at,
            delegable_audiences=frozenset(),
        )


def canonical_request_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class IdempotencyLedger:
    """In-memory semantic model; persistence and linearizability are not implied."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], tuple[str, Any]] = {}

    def record_or_replay(
        self, *, tenant: str, operation: str, key: str, payload: Any, outcome: Any
    ) -> tuple[str, Any]:
        if not all(isinstance(item, str) and item for item in (tenant, operation, key)):
            raise ValueError("invalid_idempotency_scope")
        scope = (tenant, operation, key)
        digest = canonical_request_hash(payload)
        existing = self._entries.get(scope)
        if existing is None:
            stored_outcome = copy.deepcopy(outcome)
            self._entries[scope] = (digest, stored_outcome)
            return "created", copy.deepcopy(stored_outcome)
        if existing[0] != digest:
            return "conflict", None
        return "replayed", copy.deepcopy(existing[1])
