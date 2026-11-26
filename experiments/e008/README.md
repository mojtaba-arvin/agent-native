# E-008 transactional outbox/inbox reference model

This experiment extends E-006 across the external-effect boundary. It is a single-node SQLite semantic model, not a broker or production persistence selection.

## Modeled transaction boundaries

1. **Producer transaction:** update producer-local state, record the idempotent effect key, and insert the outbox event atomically.
2. **Relay lease:** a relay claims an outbox event with a monotonically increasing fencing token. Expired leases can be reclaimed while the retry budget remains.
3. **Delivery:** publishing to a receiver is modeled as a separate action between claim and acknowledgement. A relay crash after receiver commit but before ack can cause redelivery.
4. **Consumer transaction:** insert the inbox deduplication record and mutate consumer-local state atomically. A duplicate event ID with the same semantic envelope is a no-op; a different payload/state key/amount is a conflict.
5. **Acknowledgement:** only the current unexpired lease owner/token can ack or reschedule. Stale relays are fenced.

The semantic envelope hash binds payload, state key, and amount. This prevents reusing an event ID with identical visible JSON but different effect parameters.

## Delivery guarantee

The model demonstrates **at-least-once delivery with idempotent consumer processing**. It does not provide exactly-once delivery to arbitrary external APIs. A remote receiver must implement its own idempotency/inbox boundary. If an external API cannot deduplicate, a crash after the remote side effect but before local acknowledgement can still produce duplicates.

## Failure tests

- Producer state/outbox rollback at two injected crash points.
- Relay crash after consumer commit and before acknowledgement.
- Expired lease reclaim with a higher fencing token.
- Duplicate delivery and inbox deduplication.
- Stale relay ack/retry rejection.
- Retry backoff and terminal retry exhaustion.
- Consumer state/inbox atomic rollback.
- Concurrent relay claims.

## Run

```sh
python -m unittest discover -s experiments/e008 -v
```

No distributed broker, multi-node database, cryptographic worker identity, external API adapter, or production deployment is implemented. No exactly-once claim is made.
