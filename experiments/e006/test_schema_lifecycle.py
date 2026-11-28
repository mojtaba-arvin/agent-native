import sqlite3
import tempfile
import unittest
from pathlib import Path

from schema_lifecycle import (
    MIGRATIONS, MigrationDrift, SchemaManager, compact_database,
    prune_terminal_records,
)


class SchemaEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "schema.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_existing_version_one_database_migrates_forward_idempotently(self):
        SchemaManager(self.path, migrations=MIGRATIONS[:1]).apply()
        with sqlite3.connect(self.path) as db:
            db.execute(
                """INSERT INTO retention_records(task_id,status,finished_at)
                   VALUES ('old','completed',10)"""
            )
        self.assertEqual(SchemaManager(self.path).apply(), 2)
        self.assertEqual(SchemaManager(self.path).apply(), 2)
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT retention_class FROM retention_records WHERE task_id='old'"
            ).fetchone()
            versions = db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        self.assertEqual(row[0], "standard")
        self.assertEqual(versions, [(1,), (2,)])

    def test_applied_migration_checksum_is_immutable(self):
        SchemaManager(self.path).apply()
        changed = (
            (1, "initial_retention_records", ("CREATE TABLE replacement(id TEXT)",)),
            *MIGRATIONS[1:],
        )
        with self.assertRaisesRegex(MigrationDrift, "checksum_changed:1"):
            SchemaManager(self.path, migrations=changed).apply()

    def test_failed_migration_rolls_back_schema_and_version_marker(self):
        broken = (
            MIGRATIONS[0],
            (2, "broken", ("ALTER TABLE missing_table ADD COLUMN bad TEXT",)),
        )
        with self.assertRaises(sqlite3.OperationalError):
            SchemaManager(self.path, migrations=broken).apply()
        with sqlite3.connect(self.path) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertNotIn("schema_migrations", tables)
        self.assertNotIn("retention_records", tables)


class RetentionAndCompactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "retention.sqlite3"
        SchemaManager(self.path).apply()
        with sqlite3.connect(self.path) as db:
            db.executemany(
                """INSERT INTO retention_records(task_id,status,finished_at,pinned)
                   VALUES (?,?,?,?)""",
                [
                    ("old-completed", "completed", 10, 0),
                    ("old-failed", "failed", 10, 0),
                    ("old-pinned", "completed", 10, 1),
                    ("recent", "completed", 99, 0),
                    ("running", "running", None, 0),
                    ("queued", "queued", None, 0),
                ],
            )
            db.executemany(
                "INSERT INTO retention_records(task_id,status,finished_at,pinned) VALUES (?,?,?,?)",
                [(f"padding-{i}", "cancelled", 10, 0) for i in range(200)],
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_retention_removes_only_expired_unpinned_terminal_rows(self):
        removed = prune_terminal_records(self.path, finished_before=50)
        self.assertEqual(removed, 202)
        with sqlite3.connect(self.path) as db:
            remaining = dict(db.execute(
                "SELECT task_id,status FROM retention_records"
            ).fetchall())
        self.assertEqual(set(remaining), {"old-pinned", "recent", "running", "queued"})

    def test_compaction_checkpoints_and_integrity_checks_database(self):
        result = compact_database(self.path)
        self.assertEqual(result["integrity_check"], "ok")
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM retention_records").fetchone()[0], 206)


if __name__ == "__main__":
    unittest.main()
