from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class OutboxConflict(Exception):
    pass


class StaleOutboxLease(Exception):
    pass


def _canonical(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid_{name}")


def _require_int(value: object, name: str, *, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"invalid_{name}")


class OutboxInbox:
    """SQLite reference model for transactional outbox, fenced relay, and consumer inbox."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS producer_state (
                    state_key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS producer_effects (
                    effect_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    event_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'leased', 'delivered', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 8,
                    available_at INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_token INTEGER NOT NULL DEFAULT 0,
                    lease_until INTEGER,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS consumer_state (
                    consumer_id TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value INTEGER NOT NULL,
                    PRIMARY KEY (consumer_id, state_key)
                );
                CREATE TABLE IF NOT EXISTS inbox (
                    consumer_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    applied_result_json TEXT NOT NULL,
                    applied_at INTEGER NOT NULL,
                    PRIMARY KEY (consumer_id, event_id)
                );
                """
            )
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def stage(
        self,
        *,
        effect_key: str,
        event_id: str,
        state_key: str,
        amount: int,
        payload: dict,
        now: int,
        max_attempts: int = 8,
        fail_after_state: bool = False,
        fail_after_outbox: bool = False,
    ) -> dict:
        _require_text(effect_key, "effect_key")
        _require_text(event_id, "event_id")
        _require_text(state_key, "state_key")
        _require_int(amount, "amount")
        _require_int(now, "now")
        _require_int(max_attempts, "max_attempts", minimum=1)
        if (
            not isinstance(payload, dict)
            or not isinstance(fail_after_state, bool)
            or not isinstance(fail_after_outbox, bool)
        ):
            raise ValueError("invalid_outbox_payload_or_failure_flag")
        try:
            payload_json = _canonical(payload)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_outbox_payload") from error
        payload_hash = _digest({"payload": payload, "state_key": state_key, "amount": amount})

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM producer_effects WHERE effect_key = ?", (effect_key,)
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise OutboxConflict("effect_key_payload_mismatch")
                return {"duplicate": True, "event_id": existing["event_id"]}

            event = connection.execute(
                "SELECT * FROM outbox WHERE event_id = ?", (event_id,)
            ).fetchone()
            if event is not None:
                raise OutboxConflict("event_id_already_bound")

            state = connection.execute(
                "SELECT value FROM producer_state WHERE state_key = ?", (state_key,)
            ).fetchone()
            current = state["value"] if state is not None else 0
            resulting_value = current + amount
            connection.execute(
                """INSERT INTO producer_state(state_key, value) VALUES (?, ?)
                   ON CONFLICT(state_key) DO UPDATE SET value = excluded.value""",
                (state_key, resulting_value),
            )
            if fail_after_state:
                raise RuntimeError("simulated_crash_after_producer_state")
            connection.execute(
                """INSERT INTO outbox(
                    event_id, payload_json, payload_hash, status, max_attempts, available_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)""",
                (event_id, payload_json, payload_hash, max_attempts, now),
            )
            if fail_after_outbox:
                raise RuntimeError("simulated_crash_after_outbox_insert")
            connection.execute(
                "INSERT INTO producer_effects(effect_key, payload_hash, event_id) VALUES (?, ?, ?)",
                (effect_key, payload_hash, event_id),
            )
            return {
                "duplicate": False,
                "event_id": event_id,
                "producer_value": resulting_value,
            }

    def claim(self, *, worker_id: str, now: int, lease_seconds: int) -> dict | None:
        _require_text(worker_id, "worker_id")
        _require_int(now, "now")
        _require_int(lease_seconds, "lease_seconds", minimum=1)
        with self._transaction() as connection:
            connection.execute(
                """UPDATE outbox SET status = 'failed', lease_owner = NULL,
                   lease_until = NULL, last_error = 'retry_exhausted'
                   WHERE status = 'leased' AND lease_until <= ? AND attempts >= max_attempts""",
                (now,),
            )
            row = connection.execute(
                """SELECT * FROM outbox
                   WHERE available_at <= ?
                     AND attempts < max_attempts
                     AND (status = 'pending' OR (status = 'leased' AND lease_until <= ?))
                   ORDER BY available_at, event_id LIMIT 1""",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            token = row["lease_token"] + 1
            attempts = row["attempts"] + 1
            connection.execute(
                """UPDATE outbox SET status = 'leased', attempts = ?, lease_owner = ?,
                   lease_token = ?, lease_until = ?, last_error = NULL WHERE event_id = ?""",
                (attempts, worker_id, token, now + lease_seconds, row["event_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM outbox WHERE event_id = ?", (row["event_id"],)
            ).fetchone()
            result = dict(claimed)
            result["payload"] = json.loads(result.pop("payload_json"))
            return result

    def ack(self, *, event_id: str, worker_id: str, lease_token: int, now: int) -> bool:
        _require_text(event_id, "event_id")
        _require_text(worker_id, "worker_id")
        _require_int(lease_token, "lease_token", minimum=1)
        _require_int(now, "now")
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE outbox SET status = 'delivered', lease_owner = NULL,
                   lease_until = NULL WHERE event_id = ? AND status = 'leased'
                   AND lease_owner = ? AND lease_token = ? AND lease_until > ?""",
                (event_id, worker_id, lease_token, now),
            )
            if cursor.rowcount != 1:
                raise StaleOutboxLease("outbox_lease_missing_expired_or_fenced")
            return True

    def retry(
        self, *, event_id: str, worker_id: str, lease_token: int,
        now: int, delay_seconds: int, error_code: str,
    ) -> bool:
        _require_text(event_id, "event_id")
        _require_text(worker_id, "worker_id")
        _require_int(lease_token, "lease_token", minimum=1)
        _require_int(now, "now")
        _require_int(delay_seconds, "delay_seconds")
        _require_text(error_code, "error_code")
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT attempts, max_attempts FROM outbox
                   WHERE event_id = ? AND status = 'leased' AND lease_owner = ?
                     AND lease_token = ? AND lease_until > ?""",
                (event_id, worker_id, lease_token, now),
            ).fetchone()
            if row is None:
                raise StaleOutboxLease("outbox_lease_missing_expired_or_fenced")
            if row["attempts"] >= row["max_attempts"]:
                connection.execute(
                    """UPDATE outbox SET status = 'failed', lease_owner = NULL,
                       lease_until = NULL, last_error = ? WHERE event_id = ?""",
                    (error_code, event_id),
                )
                return False
            connection.execute(
                """UPDATE outbox SET status = 'pending', available_at = ?,
                   lease_owner = NULL, lease_until = NULL, last_error = ?
                   WHERE event_id = ?""",
                (now + delay_seconds, error_code, event_id),
            )
            return True

    def consume(
        self,
        *,
        consumer_id: str,
        event_id: str,
        payload: dict,
        state_key: str,
        amount: int,
        now: int,
        fail_after_state: bool = False,
    ) -> dict:
        _require_text(consumer_id, "consumer_id")
        _require_text(event_id, "event_id")
        _require_text(state_key, "state_key")
        _require_int(amount, "amount")
        _require_int(now, "now")
        if not isinstance(payload, dict) or not isinstance(fail_after_state, bool):
            raise ValueError("invalid_consumer_payload_or_failure_flag")
        try:
            payload_json = _canonical(payload)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_consumer_payload") from error
        payload_hash = _digest({"payload": payload, "state_key": state_key, "amount": amount})

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM inbox WHERE consumer_id = ? AND event_id = ?",
                (consumer_id, event_id),
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise OutboxConflict("inbox_event_payload_mismatch")
                return {
                    "duplicate": True,
                    "result": json.loads(existing["applied_result_json"]),
                }

            state = connection.execute(
                "SELECT value FROM consumer_state WHERE consumer_id = ? AND state_key = ?",
                (consumer_id, state_key),
            ).fetchone()
            current = state["value"] if state is not None else 0
            resulting_value = current + amount
            connection.execute(
                """INSERT INTO consumer_state(consumer_id, state_key, value)
                   VALUES (?, ?, ?)
                   ON CONFLICT(consumer_id, state_key) DO UPDATE SET value = excluded.value""",
                (consumer_id, state_key, resulting_value),
            )
            if fail_after_state:
                raise RuntimeError("simulated_crash_after_consumer_state")
            result = {"consumer_id": consumer_id, "state_key": state_key, "value": resulting_value}
            connection.execute(
                """INSERT INTO inbox(
                    consumer_id, event_id, payload_hash, applied_result_json, applied_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (consumer_id, event_id, payload_hash, _canonical(result), now),
            )
            return {"duplicate": False, "result": result}

    def get_producer_state(self, state_key: str) -> int:
        _require_text(state_key, "state_key")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT value FROM producer_state WHERE state_key = ?", (state_key,)
            ).fetchone()
            return row["value"] if row is not None else 0
        finally:
            connection.close()

    def get_consumer_state(self, consumer_id: str, state_key: str) -> int:
        _require_text(consumer_id, "consumer_id")
        _require_text(state_key, "state_key")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT value FROM consumer_state WHERE consumer_id = ? AND state_key = ?",
                (consumer_id, state_key),
            ).fetchone()
            return row["value"] if row is not None else 0
        finally:
            connection.close()

    def get_outbox(self, event_id: str) -> dict | None:
        _require_text(event_id, "event_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM outbox WHERE event_id = ?", (event_id,)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            return result
        finally:
            connection.close()

    def get_inbox(self, consumer_id: str, event_id: str) -> dict | None:
        _require_text(consumer_id, "consumer_id")
        _require_text(event_id, "event_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM inbox WHERE consumer_id = ? AND event_id = ?",
                (consumer_id, event_id),
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()
