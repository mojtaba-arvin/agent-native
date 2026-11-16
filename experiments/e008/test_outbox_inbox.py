import tempfile
import threading
import unittest
from pathlib import Path

from outbox_inbox import OutboxConflict, OutboxInbox, StaleOutboxLease


class OutboxInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = OutboxInbox(Path(self.temp.name) / "outbox.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def stage(self, *, effect="effect-1", event="event-1", payload=None, amount=7, **kwargs):
        return self.store.stage(
            effect_key=effect,
            event_id=event,
            state_key="balance",
            amount=amount,
            payload={"kind": "ledger.posted"} if payload is None else payload,
            now=10,
            **kwargs,
        )

    def test_producer_state_and_outbox_insert_roll_back_together(self):
        for flag in ("fail_after_state", "fail_after_outbox"):
            with self.subTest(flag=flag):
                with self.assertRaisesRegex(RuntimeError, "simulated_crash"):
                    self.stage(effect=f"effect-{flag}", event=f"event-{flag}", **{flag: True})
                self.assertEqual(self.store.get_producer_state("balance"), 0)
                self.assertIsNone(self.store.get_outbox(f"event-{flag}"))

    def test_effect_submission_is_idempotent_and_payload_conflicts_are_rejected(self):
        first = self.stage()
        duplicate = self.stage(event="ignored-event")
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["event_id"], "event-1")
        self.assertEqual(self.store.get_producer_state("balance"), 7)
        with self.assertRaises(OutboxConflict):
            self.stage(payload={"kind": "different"})

    def test_event_id_cannot_be_rebound_to_another_effect(self):
        self.stage()
        with self.assertRaisesRegex(OutboxConflict, "event_id_already_bound"):
            self.stage(effect="effect-2")

    def test_publish_before_ack_crash_redelivers_but_inbox_applies_once(self):
        payload = {"kind": "ledger.posted", "reference": "invoice-42"}
        self.stage(payload=payload)
        first_relay = self.store.claim(worker_id="relay-a", now=10, lease_seconds=5)
        self.assertEqual(first_relay["lease_token"], 1)

        first_delivery = self.store.consume(
            consumer_id="ledger-projection",
            event_id="event-1",
            payload=payload,
            state_key="balance",
            amount=7,
            now=11,
        )
        self.assertFalse(first_delivery["duplicate"])
        self.assertEqual(self.store.get_consumer_state("ledger-projection", "balance"), 7)
        # Simulate relay crash after receiver commit but before broker acknowledgement.
        second_relay = self.store.claim(worker_id="relay-b", now=15, lease_seconds=5)
        self.assertEqual(second_relay["lease_token"], 2)

        redelivery = self.store.consume(
            consumer_id="ledger-projection",
            event_id="event-1",
            payload=payload,
            state_key="balance",
            amount=7,
            now=16,
        )
        self.assertTrue(redelivery["duplicate"])
        self.assertEqual(self.store.get_consumer_state("ledger-projection", "balance"), 7)
        self.assertTrue(self.store.ack(
            event_id="event-1", worker_id="relay-b",
            lease_token=second_relay["lease_token"], now=16,
        ))
        with self.assertRaises(StaleOutboxLease):
            self.store.ack(
                event_id="event-1", worker_id="relay-a",
                lease_token=first_relay["lease_token"], now=16,
            )
        self.assertEqual(self.store.get_outbox("event-1")["status"], "delivered")

    def test_stale_relay_cannot_ack_or_retry_after_reclaim(self):
        self.stage()
        first = self.store.claim(worker_id="relay-a", now=10, lease_seconds=5)
        second = self.store.claim(worker_id="relay-b", now=15, lease_seconds=5)
        self.assertEqual(second["lease_token"], first["lease_token"] + 1)
        with self.assertRaises(StaleOutboxLease):
            self.store.retry(
                event_id="event-1", worker_id="relay-a",
                lease_token=first["lease_token"], now=16,
                delay_seconds=1, error_code="timeout",
            )
        self.assertTrue(self.store.ack(
            event_id="event-1", worker_id="relay-b",
            lease_token=second["lease_token"], now=16,
        ))

    def test_retry_backoff_prevents_early_reclaim(self):
        self.stage()
        claimed = self.store.claim(worker_id="relay-a", now=10, lease_seconds=10)
        self.store.retry(
            event_id="event-1", worker_id="relay-a",
            lease_token=claimed["lease_token"], now=11,
            delay_seconds=5, error_code="receiver_unavailable",
        )
        self.assertIsNone(self.store.claim(worker_id="relay-b", now=15, lease_seconds=5))
        next_claim = self.store.claim(worker_id="relay-b", now=16, lease_seconds=5)
        self.assertEqual(next_claim["lease_token"], 2)
        self.assertEqual(next_claim["attempts"], 2)

    def test_consumer_state_and_inbox_insert_roll_back_together(self):
        payload = {"kind": "ledger.posted"}
        with self.assertRaisesRegex(RuntimeError, "simulated_crash"):
            self.store.consume(
                consumer_id="projection", event_id="event-1", payload=payload,
                state_key="balance", amount=4, now=10, fail_after_state=True,
            )
        self.assertEqual(self.store.get_consumer_state("projection", "balance"), 0)
        self.assertIsNone(self.store.get_inbox("projection", "event-1"))
        self.store.consume(
            consumer_id="projection", event_id="event-1", payload=payload,
            state_key="balance", amount=4, now=11,
        )
        self.assertEqual(self.store.get_consumer_state("projection", "balance"), 4)

    def test_inbox_rejects_same_event_id_with_different_semantics(self):
        self.store.consume(
            consumer_id="projection", event_id="event-1", payload={"kind": "x"},
            state_key="balance", amount=4, now=10,
        )
        with self.assertRaisesRegex(OutboxConflict, "inbox_event_payload_mismatch"):
            self.store.consume(
                consumer_id="projection", event_id="event-1", payload={"kind": "x"},
                state_key="balance", amount=5, now=11,
            )

    def test_two_relays_cannot_claim_the_same_pending_event(self):
        self.stage()
        barrier = threading.Barrier(3)
        results = []

        def relay(worker_id):
            barrier.wait()
            results.append(self.store.claim(worker_id=worker_id, now=10, lease_seconds=5))

        threads = [
            threading.Thread(target=relay, args=("relay-a",)),
            threading.Thread(target=relay, args=("relay-b",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(result is not None for result in results), 1)

    def test_non_finite_payload_and_boolean_amount_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_outbox_payload"):
            self.stage(payload={"amount": float("nan")})
        with self.assertRaisesRegex(ValueError, "invalid_amount"):
            self.stage(amount=True)



    def test_relay_retry_budget_ends_in_terminal_failed_state(self):
        self.stage(max_attempts=1)
        claimed = self.store.claim(worker_id="relay-a", now=10, lease_seconds=5)
        self.assertFalse(self.store.retry(
            event_id="event-1", worker_id="relay-a",
            lease_token=claimed["lease_token"], now=11,
            delay_seconds=1, error_code="receiver_failed",
        ))
        self.assertEqual(self.store.get_outbox("event-1")["status"], "failed")
        self.assertIsNone(self.store.claim(worker_id="relay-b", now=20, lease_seconds=5))

    def test_expired_final_lease_is_not_reclaimed_after_attempt_budget(self):
        self.stage(max_attempts=1)
        self.store.claim(worker_id="relay-a", now=10, lease_seconds=5)
        self.assertIsNone(self.store.claim(worker_id="relay-b", now=15, lease_seconds=5))
        self.assertEqual(self.store.get_outbox("event-1")["status"], "failed")

if __name__ == "__main__":
    unittest.main()
