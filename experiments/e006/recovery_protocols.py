from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


class SimulatedProcessCrash(RuntimeError):
    """A crash at a named boundary; the durable stores remain independent."""


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


class ExternalEffectHarness:
    """Executable outbox/inbox model using two independent SQLite files.

    The broker database deliberately has no uniqueness constraint on event_id:
    it models a broker that can accept duplicate publications. The consumer's
    inbox and local effect share one transaction. This does not model a remote
    provider's idempotency implementation or create a distributed transaction.
    """

    def __init__(self, application_db: str | Path, broker_db: str | Path):
        self.application_db = str(application_db)
        self.broker_db = str(broker_db)
        with _connect(self.application_db) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_facts (
                    fact_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    event_id TEXT PRIMARY KEY,
                    fact_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','publishing','published')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_token INTEGER NOT NULL DEFAULT 0,
                    lease_until INTEGER,
                    published_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS outbox_due
                    ON outbox(status, lease_until, event_id);
                CREATE TABLE IF NOT EXISTS inbox (
                    consumer TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    processed_at INTEGER NOT NULL,
                    PRIMARY KEY(consumer, event_id)
                );
                CREATE TABLE IF NOT EXISTS consumer_effects (
                    consumer TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    effect_value INTEGER NOT NULL,
                    PRIMARY KEY(consumer, event_id)
                );
                """
            )
        with _connect(self.broker_db) as broker:
            broker.execute("PRAGMA journal_mode=WAL")
            broker.executescript(
                """
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def submit(self, *, fact_id: str, event_id: str, payload: dict) -> None:
        if not fact_id.strip() or not event_id.strip() or not isinstance(payload, dict):
            raise ValueError("invalid_external_effect_submission")
        payload_json = _json(payload)
        db = _connect(self.application_db)
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload_json FROM outbox WHERE event_id=?", (event_id,)).fetchone()
            if old is not None:
                if old["payload_json"] != payload_json:
                    raise ValueError("event_id_payload_conflict")
                db.commit()
                return
            db.execute("INSERT INTO business_facts(fact_id,payload_json) VALUES (?,?)",
                       (fact_id, payload_json))
            db.execute(
                """INSERT INTO outbox(event_id,fact_id,payload_json,status)
                   VALUES (?,?,?,'pending')""",
                (event_id, fact_id, payload_json),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def publish_one(self, *, worker: str, now: int, lease_seconds: int,
                    crash_after_broker_ack: bool = False) -> str | None:
        """Publish at least once; a crash before local mark intentionally duplicates."""
        db = _connect(self.application_db)
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM outbox
                   WHERE status='pending' OR (status='publishing' AND lease_until<=?)
                   ORDER BY event_id LIMIT 1""", (now,)
            ).fetchone()
            if row is None:
                db.commit()
                return None
            token = row["lease_token"] + 1
            db.execute(
                """UPDATE outbox SET status='publishing', attempts=attempts+1,
                   lease_owner=?, lease_token=?, lease_until=? WHERE event_id=?""",
                (worker, token, now + lease_seconds, row["event_id"]),
            )
            event_id, payload_json = row["event_id"], row["payload_json"]
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        # Independent commit: there is deliberately no cross-database transaction.
        with _connect(self.broker_db) as broker:
            broker.execute(
                "INSERT INTO deliveries(event_id,payload_json) VALUES (?,?)",
                (event_id, payload_json),
            )
        if crash_after_broker_ack:
            raise SimulatedProcessCrash("crash_after_broker_ack_before_outbox_mark")

        db = _connect(self.application_db)
        try:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                """UPDATE outbox SET status='published', published_at=?,
                   lease_owner=NULL, lease_until=NULL
                   WHERE event_id=? AND status='publishing'
                     AND lease_owner=? AND lease_token=?""",
                (now, event_id, worker, token),
            ).rowcount
            db.commit()
            if changed != 1:
                raise RuntimeError("outbox_lease_fenced_after_publish")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return event_id

    def consume(self, *, delivery_id: int, consumer: str, now: int,
                crash_before_broker_ack: bool = False) -> bool:
        """Return True for a new effect; duplicates are acknowledged without reapplying."""
        with _connect(self.broker_db) as broker:
            delivery = broker.execute(
                "SELECT * FROM deliveries WHERE delivery_id=?", (delivery_id,)
            ).fetchone()
        if delivery is None:
            raise KeyError(delivery_id)
        payload_hash = hashlib.sha256(delivery["payload_json"].encode()).hexdigest()
        db = _connect(self.application_db)
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT payload_hash FROM inbox WHERE consumer=? AND event_id=?",
                (consumer, delivery["event_id"]),
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise ValueError("inbox_event_payload_conflict")
                applied = False
            else:
                payload = json.loads(delivery["payload_json"])
                value = payload.get("increment", 1)
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError("invalid_consumer_effect")
                db.execute(
                    "INSERT INTO inbox(consumer,event_id,payload_hash,processed_at) VALUES (?,?,?,?)",
                    (consumer, delivery["event_id"], payload_hash, now),
                )
                db.execute(
                    "INSERT INTO consumer_effects(consumer,event_id,effect_value) VALUES (?,?,?)",
                    (consumer, delivery["event_id"], value),
                )
                applied = True
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        if crash_before_broker_ack:
            raise SimulatedProcessCrash("crash_after_consumer_commit_before_ack")
        with _connect(self.broker_db) as broker:
            broker.execute("UPDATE deliveries SET acknowledged=1 WHERE delivery_id=?", (delivery_id,))
        return applied

    def effect_total(self, consumer: str) -> int:
        with _connect(self.application_db) as db:
            row = db.execute(
                "SELECT COALESCE(SUM(effect_value),0) AS total FROM consumer_effects WHERE consumer=?",
                (consumer,),
            ).fetchone()
            return int(row["total"])

    def deliveries(self) -> list[dict]:
        with _connect(self.broker_db) as db:
            return [dict(row) for row in db.execute("SELECT * FROM deliveries ORDER BY delivery_id")]
