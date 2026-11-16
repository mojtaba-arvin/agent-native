from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class IdempotencyConflict(Exception):
    pass


class StaleLease(Exception):
    pass


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class DurableQueue:
    """SQLite reference model for durable tasks, fenced leases, and local atomic effects."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('queued', 'running', 'completed', 'failed', 'cancelled')
                    ),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    deadline_at INTEGER NOT NULL,
                    available_at INTEGER NOT NULL,
                    lease_owner TEXT,
                    lease_token INTEGER NOT NULL DEFAULT 0,
                    lease_until INTEGER,
                    result_json TEXT,
                    error_code TEXT
                );
                CREATE TABLE IF NOT EXISTS local_state (
                    state_key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS effect_ledger (
                    effect_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    resulting_value INTEGER NOT NULL
                );
                """
            )

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

    @staticmethod
    def _task(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["result"] = (
            json.loads(result.pop("result_json"))
            if result["result_json"] is not None
            else None
        )
        return result

    def submit(self, *, task_id: str, idempotency_key: str, payload: dict,
               now: int, deadline_at: int, max_attempts: int = 3) -> dict:
        if not task_id or not idempotency_key or max_attempts < 1 or deadline_at <= now:
            raise ValueError("invalid_task_submission")
        payload_json = _canonical(payload)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload_json:
                    raise IdempotencyConflict("idempotency_key_payload_mismatch")
                return {"duplicate": True, "task": self._task(existing)}
            connection.execute(
                """INSERT INTO tasks (
                    id, idempotency_key, payload_json, status, max_attempts,
                    deadline_at, available_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?)""",
                (task_id, idempotency_key, payload_json, max_attempts, deadline_at, now),
            )
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return {"duplicate": False, "task": self._task(row)}

    def claim(self, *, worker_id: str, now: int, lease_seconds: int) -> dict | None:
        if not worker_id or lease_seconds < 1:
            raise ValueError("invalid_lease_request")
        with self._transaction() as connection:
            connection.execute(
                """UPDATE tasks SET status = 'failed', error_code = 'deadline_exceeded',
                   lease_owner = NULL, lease_until = NULL
                   WHERE status IN ('queued', 'running') AND deadline_at <= ?""",
                (now,),
            )
            connection.execute(
                """UPDATE tasks SET status = 'failed', error_code = 'retry_exhausted',
                   lease_owner = NULL, lease_until = NULL
                   WHERE status = 'running' AND lease_until <= ? AND attempts >= max_attempts""",
                (now,),
            )
            row = connection.execute(
                """SELECT * FROM tasks
                   WHERE deadline_at > ? AND available_at <= ? AND attempts < max_attempts
                     AND (status = 'queued' OR (status = 'running' AND lease_until <= ?))
                   ORDER BY available_at, id LIMIT 1""",
                (now, now, now),
            ).fetchone()
            if row is None:
                return None
            token = row["lease_token"] + 1
            attempts = row["attempts"] + 1
            connection.execute(
                """UPDATE tasks SET status = 'running', attempts = ?, lease_owner = ?,
                   lease_token = ?, lease_until = ?, error_code = NULL WHERE id = ?""",
                (attempts, worker_id, token, now + lease_seconds, row["id"]),
            )
            claimed = connection.execute("SELECT * FROM tasks WHERE id = ?", (row["id"],)).fetchone()
            return self._task(claimed)

    def renew_lease(self, *, task_id: str, worker_id: str, lease_token: int,
                    now: int, lease_seconds: int) -> bool:
        if lease_seconds < 1:
            raise ValueError("invalid_lease_duration")
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE tasks SET lease_until = ?
                   WHERE id = ? AND status = 'running' AND lease_owner = ?
                     AND lease_token = ? AND lease_until > ? AND deadline_at > ?""",
                (now + lease_seconds, task_id, worker_id, lease_token, now, now),
            )
            return cursor.rowcount == 1

    def retry(self, *, task_id: str, worker_id: str, lease_token: int,
              now: int, delay_seconds: int) -> str:
        if delay_seconds < 0:
            raise ValueError("invalid_retry_delay")
        with self._transaction() as connection:
            row = self._owned_lease(connection, task_id, worker_id, lease_token, now)
            if row["attempts"] >= row["max_attempts"]:
                connection.execute(
                    """UPDATE tasks SET status = 'failed', error_code = 'retry_exhausted',
                       lease_owner = NULL, lease_until = NULL WHERE id = ?""", (task_id,)
                )
                return "failed"
            connection.execute(
                """UPDATE tasks SET status = 'queued', available_at = ?,
                   lease_owner = NULL, lease_until = NULL, error_code = 'retry_scheduled'
                   WHERE id = ?""",
                (now + delay_seconds, task_id),
            )
            return "queued"

    def complete_with_increment(self, *, task_id: str, worker_id: str, lease_token: int,
                                 now: int, effect_key: str, state_key: str, amount: int,
                                 fail_after_effect: bool = False) -> dict:
        if not effect_key or not state_key:
            raise ValueError("effect_and_state_keys_required")
        payload_hash = _digest({"state_key": state_key, "amount": amount})
        with self._transaction() as connection:
            self._owned_lease(connection, task_id, worker_id, lease_token, now)
            existing = connection.execute(
                "SELECT * FROM effect_ledger WHERE effect_key = ?", (effect_key,)
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise IdempotencyConflict("effect_key_payload_mismatch")
                resulting_value = existing["resulting_value"]
                replayed = True
            else:
                state = connection.execute(
                    "SELECT value FROM local_state WHERE state_key = ?", (state_key,)
                ).fetchone()
                current_value = state["value"] if state is not None else 0
                resulting_value = current_value + amount
                connection.execute(
                    """INSERT INTO local_state(state_key, value) VALUES (?, ?)
                       ON CONFLICT(state_key) DO UPDATE SET value = excluded.value""",
                    (state_key, resulting_value),
                )
                connection.execute(
                    """INSERT INTO effect_ledger(
                       effect_key, payload_hash, state_key, amount, resulting_value
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (effect_key, payload_hash, state_key, amount, resulting_value),
                )
                replayed = False
            if fail_after_effect:
                raise RuntimeError("simulated_crash_before_commit")
            result = {"state_key": state_key, "value": resulting_value, "effect_replayed": replayed}
            connection.execute(
                """UPDATE tasks SET status = 'completed', result_json = ?,
                   lease_owner = NULL, lease_until = NULL, error_code = NULL WHERE id = ?""",
                (_canonical(result), task_id),
            )
            return result

    def cancel(self, task_id: str) -> bool:
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE tasks SET status = 'cancelled', lease_owner = NULL, lease_until = NULL
                   WHERE id = ? AND status IN ('queued', 'running')""", (task_id,)
            )
            return cursor.rowcount == 1

    def expire_deadlines(self, *, now: int) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE tasks SET status = 'failed', error_code = 'deadline_exceeded',
                   lease_owner = NULL, lease_until = NULL
                   WHERE status IN ('queued', 'running') AND deadline_at <= ?""", (now,)
            )
            return cursor.rowcount

    def get_task(self, task_id: str) -> dict | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._task(row) if row is not None else None
        finally:
            connection.close()

    def get_state(self, state_key: str) -> int:
        connection = self._connect()
        try:
            row = connection.execute("SELECT value FROM local_state WHERE state_key = ?", (state_key,)).fetchone()
            return row["value"] if row is not None else 0
        finally:
            connection.close()

    def get_effect(self, effect_key: str) -> dict | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM effect_ledger WHERE effect_key = ?", (effect_key,)).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()

    @staticmethod
    def _owned_lease(connection: sqlite3.Connection, task_id: str, worker_id: str,
                     lease_token: int, now: int) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if (row is None or row["status"] != "running" or row["lease_owner"] != worker_id
                or row["lease_token"] != lease_token or row["lease_until"] is None
                or row["lease_until"] <= now or row["deadline_at"] <= now):
            raise StaleLease("lease_missing_expired_or_fenced")
        return row
