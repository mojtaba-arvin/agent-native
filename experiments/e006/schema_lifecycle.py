from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path


MIGRATIONS = (
    (
        1,
        "initial_retention_records",
        (
            """CREATE TABLE retention_records (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK(status IN
                    ('queued','running','completed','failed','cancelled')),
                finished_at INTEGER,
                pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1))
            )""",
        ),
    ),
    (
        2,
        "classify_retention_records",
        (
            "ALTER TABLE retention_records ADD COLUMN retention_class TEXT NOT NULL DEFAULT 'standard'",
            """CREATE INDEX retention_finished_idx
               ON retention_records(status, finished_at, pinned)""",
        ),
    ),
)


class MigrationDrift(RuntimeError):
    pass


def _checksum(statements: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(statements).encode()).hexdigest()


class SchemaManager:
    """Small SQLite migration harness with immutable version/checksum history."""

    def __init__(self, path: str | Path, migrations=MIGRATIONS):
        self.path = str(path)
        self.migrations = migrations

    def apply(self) -> int:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            applied = {
                row[0]: (row[1], row[2])
                for row in db.execute("SELECT version,name,checksum FROM schema_migrations")
            }
            known_versions = {migration[0] for migration in self.migrations}
            if any(version not in known_versions for version in applied):
                raise MigrationDrift("database_has_unknown_migration_version")
            latest = max(applied, default=0)
            for version, name, statements in self.migrations:
                digest = _checksum(statements)
                previous = applied.get(version)
                if previous is not None:
                    if previous != (name, digest):
                        raise MigrationDrift(f"migration_checksum_changed:{version}")
                    continue
                if version <= latest:
                    raise MigrationDrift(f"migration_history_gap:{version}")
                for statement in statements:
                    db.execute(statement)
                db.execute(
                    "INSERT INTO schema_migrations(version,name,checksum) VALUES (?,?,?)",
                    (version, name, digest),
                )
            db.commit()
            return max((migration[0] for migration in self.migrations), default=0)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def prune_terminal_records(path: str | Path, *, finished_before: int) -> int:
    """Delete only old, unpinned terminal records; never touch queued/running work."""
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute(
            """DELETE FROM retention_records
               WHERE status IN ('completed','failed','cancelled')
                 AND pinned=0 AND finished_at IS NOT NULL AND finished_at<=?""",
            (finished_before,),
        ).rowcount
        db.commit()
        return changed
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def compact_database(path: str | Path) -> dict:
    """Checkpoint WAL, compact, and verify. VACUUM is deliberately outside a txn."""
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        db.execute("VACUUM")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"sqlite_integrity_check_failed:{integrity}")
        return {
            "checkpoint_busy": int(checkpoint[0]),
            "checkpointed_frames": int(checkpoint[1]),
            "checkpoint_total_frames": int(checkpoint[2]),
            "integrity_check": integrity,
        }
    finally:
        db.close()
