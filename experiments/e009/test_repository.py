from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repository import (
    IdempotencyConflict,
    ItemConflict,
    SQLiteCatalogRepository,
)


class SQLiteCatalogRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "catalog.sqlite3"
        self.repository = SQLiteCatalogRepository(self.database)

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    def test_schema_is_migrated_and_data_survives_reopen(self):
        created, replayed = self.repository.create_item(
            tenant_id="tenant-a",
            name="DeskLamp",
            idempotency_key="create-001",
            now=100,
        )
        self.assertFalse(replayed)
        reopened = SQLiteCatalogRepository(self.database)
        found = reopened.get_item(tenant_id="tenant-a", item_id=created["id"])
        self.assertEqual(found, created)
        reopened.close()

    def test_tenant_id_is_part_of_every_repository_lookup(self):
        item, _ = self.repository.create_item(
            tenant_id="tenant-a",
            name="Private",
            idempotency_key="tenant-a-key",
            now=100,
        )
        self.assertEqual(
            self.repository.get_item(tenant_id="tenant-a", item_id=item["id"]),
            item,
        )
        self.assertIsNone(
            self.repository.get_item(tenant_id="tenant-b", item_id=item["id"])
        )
        self.assertIsNone(
            self.repository.get_item_by_name(tenant_id="tenant-b", name="Private")
        )

    def test_idempotency_key_is_scoped_to_tenant_and_payload(self):
        item, replayed = self.repository.create_item(
            tenant_id="tenant-a",
            name="Same",
            idempotency_key="same-key",
            now=100,
        )
        again, replayed_again = self.repository.create_item(
            tenant_id="tenant-a",
            name="Same",
            idempotency_key="same-key",
            now=101,
        )
        other_tenant, other_replayed = self.repository.create_item(
            tenant_id="tenant-b",
            name="Same",
            idempotency_key="same-key",
            now=101,
        )
        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(item, again)
        self.assertFalse(other_replayed)
        self.assertNotEqual(item["id"], other_tenant["id"])
        with self.assertRaises(IdempotencyConflict):
            self.repository.create_item(
                tenant_id="tenant-a",
                name="Different",
                idempotency_key="same-key",
                now=102,
            )

    def test_unique_name_constraint_is_per_tenant(self):
        self.repository.create_item(
            tenant_id="tenant-a", name="Shared", idempotency_key="a-1", now=1
        )
        with self.assertRaises(ItemConflict):
            self.repository.create_item(
                tenant_id="tenant-a", name="Shared", idempotency_key="a-2", now=1
            )
        other, replayed = self.repository.create_item(
            tenant_id="tenant-b", name="Shared", idempotency_key="b-1", now=1
        )
        self.assertFalse(replayed)
        self.assertEqual(other["name"], "Shared")

    def test_concurrent_duplicate_submissions_commit_once_and_replay(self):
        def create():
            return self.repository.create_item(
                tenant_id="tenant-a",
                name="Concurrent",
                idempotency_key="concurrent-key",
                now=200,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _index: create(), range(8)))

        identities = {item["id"] for item, _replayed in results}
        replay_flags = [replayed for _item, replayed in results]
        self.assertEqual(len(identities), 1)
        self.assertEqual(replay_flags.count(False), 1)
        self.assertEqual(replay_flags.count(True), 7)

    def test_invalid_trusted_arguments_are_rejected(self):
        for tenant, name, key, now in (
            ("", "Name", "key", 1),
            ("tenant", "", "key", 1),
            ("tenant", "Name", "", 1),
            ("tenant", "Name", "key", True),
        ):
            with self.assertRaises(ValueError):
                self.repository.create_item(
                    tenant_id=tenant,
                    name=name,
                    idempotency_key=key,
                    now=now,
                )

    def test_future_schema_version_is_rejected(self):
        import sqlite3

        connection = sqlite3.connect(self.database)
        connection.execute("PRAGMA user_version = 99")
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(Exception, "newer_than_runtime"):
            SQLiteCatalogRepository(self.database)


if __name__ == "__main__":
    unittest.main()
