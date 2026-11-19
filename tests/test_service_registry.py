from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_native import ServiceRegistry, ServiceRegistryError

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "services"
TRUSTED = {
    "crud.read",
    "crud.create",
    "crud.read_by_field",
    "crud.list",
    "crud.update",
    "crud.delete",
    "jobs.submit",
    "jobs.get",
    "jobs.cancel",
    "events.publish",
}


class ServiceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = ServiceRegistry(SERVICES, trusted_handler_ids=TRUSTED)

    def temporary_registry(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "services"
        root.mkdir()
        return temporary, root

    def copy_service(self, root: Path, name: str = "inventory") -> Path:
        target = root / name
        shutil.copytree(SERVICES / name, target)
        return target

    def test_loads_catalog_and_second_service_from_manifests(self):
        services = self.registry.load_all()
        self.assertEqual(set(services), {"catalog", "inventory"})
        self.assertEqual(services["catalog"].service_name, "Catalog")
        self.assertEqual(services["inventory"].service_name, "Inventory")
        self.assertEqual(services["inventory"].handler_bindings["list_stock"], "crud.list")
        self.assertEqual(services["inventory"].handler_configs["list_stock"]["resource"], "stock")

    def test_v1_string_bindings_remain_backward_compatible(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 1
        manifest["handlers"] = {name: spec["handler_id"] for name, spec in manifest["handlers"].items()}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        service = ServiceRegistry(root, trusted_handler_ids=TRUSTED).load("inventory")
        self.assertEqual(service.handler_bindings["list_stock"], "crud.list")
        self.assertEqual(dict(service.handler_configs["list_stock"]), {})

    def test_unknown_service_fails_closed(self):
        with self.assertRaisesRegex(ServiceRegistryError, "unknown service ID") as raised:
            self.registry.load("missing")
        self.assertEqual(raised.exception.code, "unknown_service")

    def test_invalid_service_id_fails_closed(self):
        with self.assertRaises(ServiceRegistryError) as raised:
            self.registry.load("../inventory")
        self.assertEqual(raised.exception.code, "invalid_service_id")

    def test_duplicate_service_ids_fail_closed(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        self.copy_service(root)
        duplicate = root / "duplicate"
        shutil.copytree(root / "inventory", duplicate)
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "duplicate_service_id")

    def test_unknown_handler_reference_is_rejected_without_importing_code(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["handlers"]["list_stock"] = {"handler_id": "python:os.system", "config": {}}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "untrusted_handler_id")

    def test_every_operation_requires_exactly_one_handler_binding(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["handlers"].pop("list_stock")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "handler_binding_mismatch")

    def test_windows_style_manifest_path_is_rejected(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source"] = r"..\outside.an"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "invalid_manifest_path")

    def test_boolean_manifest_schema_version_is_rejected(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = True
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "unsupported_manifest_version")

    def test_manifest_service_name_must_match_ir(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["service_name"] = "OtherService"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "service_name_mismatch")

    def test_policy_must_cover_declared_effects(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        policy_path = folder / "policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["effects"] = []
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "policy_effect_missing")

    def test_manifest_path_traversal_is_rejected(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source"] = "../outside.an"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "invalid_manifest_path")

    def test_source_symlink_is_rejected(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        original = folder / "service.an"
        outside = Path(temporary.name) / "outside.an"
        outside.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
        original.unlink()
        original.symlink_to(outside)
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "manifest_path_symlink")

    def test_manifest_version_must_match_service_ir(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        manifest_path = folder / "service.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "2"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "service_version_mismatch")

    def test_policy_must_default_to_deny(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        policy_path = folder / "policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["default_decision"] = "allow"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "policy_not_default_deny")

    def test_policy_must_cover_all_declared_capabilities_and_effects(self):
        temporary, root = self.temporary_registry()
        self.addCleanup(temporary.cleanup)
        folder = self.copy_service(root)
        policy_path = folder / "policy.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy["capabilities"] = []
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaises(ServiceRegistryError) as raised:
            ServiceRegistry(root, trusted_handler_ids=TRUSTED).load_all()
        self.assertEqual(raised.exception.code, "policy_capability_missing")


if __name__ == "__main__":
    unittest.main()
