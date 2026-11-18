from __future__ import annotations

import random
import unittest

from semantics import (
    CallLifecycle, CallState, Capability, DeadlineBudget,
    IdempotencyLedger, InvalidTransition, retry_action,
)


class CallLifecycleTests(unittest.TestCase):
    def test_seeded_transition_fuzz_preserves_the_state_machine(self):
        allowed = {
            CallState.CREATED: {
                CallState.REJECTED_BEFORE_DISPATCH, CallState.ACCEPTED,
                CallState.FAILED_BEFORE_EFFECT, CallState.OUTCOME_UNKNOWN,
            },
            CallState.ACCEPTED: {
                CallState.COMPLETED, CallState.FAILED_BEFORE_EFFECT,
                CallState.CANCEL_REQUESTED, CallState.OUTCOME_UNKNOWN,
            },
            CallState.CANCEL_REQUESTED: {
                CallState.CANCELLED_AND_STOPPED, CallState.COMPLETED,
                CallState.OUTCOME_UNKNOWN,
            },
            CallState.OUTCOME_UNKNOWN: {
                CallState.ACCEPTED, CallState.COMPLETED,
                CallState.FAILED_BEFORE_EFFECT, CallState.CANCEL_REQUESTED,
                CallState.CANCELLED_AND_STOPPED,
            },
            CallState.REJECTED_BEFORE_DISPATCH: set(),
            CallState.COMPLETED: set(),
            CallState.FAILED_BEFORE_EFFECT: set(),
            CallState.CANCELLED_AND_STOPPED: set(),
        }
        rng = random.Random(20261118)
        call = CallLifecycle()
        for _ in range(10_000):
            candidate = rng.choice(list(CallState))
            before_state, before_history = call.state, call.history
            if candidate in allowed[before_state]:
                call.transition(candidate)
                self.assertEqual(call.state, candidate)
                self.assertEqual(call.history, (*before_history, candidate))
            else:
                with self.assertRaises(InvalidTransition):
                    call.transition(candidate)
                self.assertEqual(call.state, before_state)
                self.assertEqual(call.history, before_history)
            self.assertEqual(call.history[-1], call.state)

    def test_lost_response_after_commit_reconciles_same_key(self):
        call = CallLifecycle()
        call.transition(CallState.ACCEPTED)
        call.transition(CallState.OUTCOME_UNKNOWN)
        self.assertEqual(retry_action(call.state, operation_retryable=True), "reconcile_same_key")
        call.transition(CallState.COMPLETED)
        self.assertEqual(retry_action(call.state, operation_retryable=True), "return_recorded_outcome")

    def test_rejected_before_dispatch_is_distinct_from_unknown(self):
        rejected = CallLifecycle()
        rejected.transition(CallState.REJECTED_BEFORE_DISPATCH)
        self.assertEqual(retry_action(rejected.state, operation_retryable=True), "retry_new_attempt")
        unknown = CallLifecycle()
        unknown.transition(CallState.OUTCOME_UNKNOWN)
        self.assertEqual(retry_action(unknown.state, operation_retryable=True), "reconcile_same_key")

    def test_cancellation_does_not_mean_stopped_until_acknowledged(self):
        call = CallLifecycle()
        call.transition(CallState.ACCEPTED)
        call.transition(CallState.CANCEL_REQUESTED)
        self.assertEqual(retry_action(call.state, operation_retryable=True), "reconcile_same_key")
        call.transition(CallState.CANCELLED_AND_STOPPED)
        self.assertEqual(retry_action(call.state, operation_retryable=True), "return_recorded_outcome")

    def test_invalid_terminal_transition_is_rejected(self):
        call = CallLifecycle()
        call.transition(CallState.ACCEPTED)
        call.transition(CallState.COMPLETED)
        with self.assertRaises(InvalidTransition):
            call.transition(CallState.ACCEPTED)


class DeadlineTests(unittest.TestCase):
    def test_receiver_caps_and_each_hop_subtracts_elapsed_time(self):
        budget = DeadlineBudget.receive(900, local_cap_ms=500)
        self.assertEqual(budget.after_elapsed(120).remaining_ms, 380)
        self.assertEqual(budget.after_elapsed(700).remaining_ms, 0)


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.parent = Capability(
            issuer="issuer", subject="service-a", audience="service-b",
            tenant="tenant-a", operations=frozenset({"read", "write"}),
            resources=frozenset({"item:1", "item:2"}), expires_at=1000,
            delegable_audiences=frozenset({"service-c"}),
        )

    def test_attenuation_only_narrows_authority(self):
        child = self.parent.attenuate(
            audience="service-c", operations=frozenset({"read"}),
            resources=frozenset({"item:1"}), expires_at=900,
        )
        self.assertLessEqual(child.operations, self.parent.operations)
        self.assertLessEqual(child.resources, self.parent.resources)
        self.assertLessEqual(child.expires_at, self.parent.expires_at)
        self.assertEqual(child.tenant, self.parent.tenant)

    def test_escalation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "audience_escalation"):
            self.parent.attenuate(
                audience="untrusted-service", operations=frozenset({"read"}),
                resources=frozenset({"item:1"}), expires_at=900,
            )
        with self.assertRaisesRegex(ValueError, "operation_escalation"):
            self.parent.attenuate(
                audience="service-c", operations=frozenset({"admin"}),
                resources=frozenset({"item:1"}), expires_at=900,
            )
        with self.assertRaisesRegex(ValueError, "resource_escalation"):
            self.parent.attenuate(
                audience="service-c", operations=frozenset({"read"}),
                resources=frozenset({"*"}), expires_at=900,
            )
        with self.assertRaisesRegex(ValueError, "expiry_escalation"):
            self.parent.attenuate(
                audience="service-c", operations=frozenset({"read"}),
                resources=frozenset({"item:1"}), expires_at=1001,
            )


class IdempotencyTests(unittest.TestCase):
    def test_stored_and_returned_outcomes_are_defensively_copied(self):
        ledger = IdempotencyLedger()
        original = {"job": {"id": "j1", "labels": ["accepted"]}}
        status, returned = ledger.record_or_replay(
            tenant="t1", operation="create", key="k-copy",
            payload={"name": "lamp"}, outcome=original,
        )
        self.assertEqual(status, "created")
        original["job"]["labels"].append("caller-mutated")
        returned["job"]["id"] = "caller-mutated"
        replay_status, replayed = ledger.record_or_replay(
            tenant="t1", operation="create", key="k-copy",
            payload={"name": "lamp"}, outcome={"job": {"id": "j2"}},
        )
        self.assertEqual(replay_status, "replayed")
        self.assertEqual(replayed, {"job": {"id": "j1", "labels": ["accepted"]}})

    def test_same_key_same_payload_replays_original_outcome(self):
        ledger = IdempotencyLedger()
        first = ledger.record_or_replay(
            tenant="t1", operation="create", key="k1",
            payload={"name": "lamp"}, outcome={"job_id": "j1"},
        )
        replay = ledger.record_or_replay(
            tenant="t1", operation="create", key="k1",
            payload={"name": "lamp"}, outcome={"job_id": "j2"},
        )
        self.assertEqual(first, ("created", {"job_id": "j1"}))
        self.assertEqual(replay, ("replayed", {"job_id": "j1"}))

    def test_same_key_different_payload_conflicts_and_scope_isolated(self):
        ledger = IdempotencyLedger()
        ledger.record_or_replay(
            tenant="t1", operation="create", key="k1",
            payload={"name": "lamp"}, outcome={"job_id": "j1"},
        )
        conflict = ledger.record_or_replay(
            tenant="t1", operation="create", key="k1",
            payload={"name": "desk"}, outcome={"job_id": "j2"},
        )
        other_tenant = ledger.record_or_replay(
            tenant="t2", operation="create", key="k1",
            payload={"name": "desk"}, outcome={"job_id": "j3"},
        )
        self.assertEqual(conflict, ("conflict", None))
        self.assertEqual(other_tenant[0], "created")


if __name__ == "__main__":
    unittest.main()
