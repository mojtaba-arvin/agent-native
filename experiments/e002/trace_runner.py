"""Deterministic generated semantic traces shared by E-002 storage adapters."""
from __future__ import annotations

import hashlib
import json
import random


TRACE_SEED = 20261118
TRACE_OPERATIONS = 60


def run_reference_trace(adapter, *, seed: int = TRACE_SEED, operations: int = TRACE_OPERATIONS):
    rng = random.Random(seed)
    first_payloads = {}
    original_outcomes = {}
    status_sequence = []
    status_counts = {"created": 0, "replayed": 0, "conflict": 0}

    for index in range(operations):
        tenant_id = rng.choice(("tenant-a", "tenant-b"))
        operation_id = rng.choice(("jobs.create", "jobs.rebuild"))
        idempotency_key = f"key-{rng.randrange(6)}"
        payload = {
            "resource": rng.choice(("lamp", "desk", "chair", "shelf")),
            "version": rng.randrange(1, 4),
        }
        scope = (tenant_id, operation_id, idempotency_key)
        previous = first_payloads.get(scope)
        if previous is None:
            expected_status = "created"
        elif previous == payload:
            expected_status = "replayed"
        else:
            expected_status = "conflict"

        status, outcome = adapter.admit_job(
            tenant_id=tenant_id,
            operation_id=operation_id,
            idempotency_key=idempotency_key,
            payload=payload,
            outbox_payload={"topic": operation_id, "payload": payload},
            audit_event={
                "request_id": f"generated-trace-{index:03d}",
                "operation_id": operation_id,
                "created_at": 1000 + index,
            },
        )
        if status != expected_status:
            raise AssertionError(
                f"trace operation {index}: expected {expected_status}, got {status}"
            )
        if status == "created":
            first_payloads[scope] = payload
            original_outcomes[scope] = outcome
        elif status == "replayed":
            if outcome != original_outcomes[scope]:
                raise AssertionError(f"trace operation {index}: replay outcome changed")
        elif outcome.get("code") != "IDEMPOTENCY_PAYLOAD_CONFLICT":
            raise AssertionError(f"trace operation {index}: wrong conflict outcome")

        status_sequence.append(status)
        status_counts[status] += 1

    for (tenant_id, operation_id, key), outcome in original_outcomes.items():
        record = adapter.lookup_idempotency(tenant_id, operation_id, key)
        if record is None or record["outcome"] != outcome:
            raise AssertionError("idempotency lookup diverged from original admission")
        job = adapter.read_job(outcome["job_id"])
        if job is None or job["state"] != "queued":
            raise AssertionError("durable job missing or in unexpected state")
        if adapter.read_outbox_for_job(outcome["job_id"]) is None:
            raise AssertionError("durable outbox record missing")

    claimed = adapter.claim_outbox(
        consumer="generated-trace-relay",
        limit=operations + 1,
        lease_seconds=30,
        now=5000,
    )
    if len(claimed) != len(original_outcomes):
        raise AssertionError("outbox claim count differs from created job count")
    reclaimed = adapter.claim_outbox(
        consumer="generated-trace-relay-recovery",
        limit=operations + 1,
        lease_seconds=30,
        now=5030,
    )
    if len(reclaimed) != len(claimed):
        raise AssertionError("expired outbox lease was not reclaimed")
    reclaimed_by_id = {str(event["event_id"]): event for event in reclaimed}
    stale_ack_rejected = 0
    acked = 0
    for event in claimed:
        event_id = str(event["event_id"])
        current = reclaimed_by_id.get(event_id)
        if current is None:
            raise AssertionError("reclaimed outbox event identity changed")
        if not adapter.ack_outbox(
            event_id=event_id,
            consumer="generated-trace-relay",
            lease_token=event["lease_token"],
            now=5031,
        ):
            stale_ack_rejected += 1
        if adapter.ack_outbox(
            event_id=event_id,
            consumer="generated-trace-relay-recovery",
            lease_token=current["lease_token"],
            now=5031,
        ):
            acked += 1
    if stale_ack_rejected != len(claimed):
        raise AssertionError("stale outbox lease acknowledgements were not all fenced")
    if acked != len(original_outcomes):
        raise AssertionError("reclaimed outbox acknowledgement count differs from created job count")

    raw_counts = adapter.recover()
    counts = {key.removeprefix("e002_"): value for key, value in raw_counts.items()}
    expected_counts = {
        "jobs": len(original_outcomes),
        "outbox": len(original_outcomes),
        "idempotency_records": len(original_outcomes),
        "audit": operations,
    }
    if counts != expected_counts:
        raise AssertionError(f"durable record counts diverged: {counts!r}")

    canonical_result = {
        "seed": seed,
        "operations": operations,
        "status_sequence": status_sequence,
        "status_counts": status_counts,
        "record_counts": counts,
        "outbox_claimed": len(claimed),
        "stale_ack_rejected": stale_ack_rejected,
        "outbox_acked": acked,
    }
    canonical = json.dumps(
        canonical_result, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    canonical_result["trace_digest"] = hashlib.sha256(canonical).hexdigest()
    return canonical_result
