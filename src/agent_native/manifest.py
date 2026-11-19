"""Manifest-backed, fail-closed service discovery.

The registry resolves only explicit declarative manifests. It never imports
Python modules or executes manifest-provided code.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from .ir import Diagnostic, Parser


class ServiceRegistryError(Exception):
    """A stable, machine-readable service discovery or validation failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RegisteredService:
    service_id: str
    service_name: str
    version: str
    source_path: Path
    ir: Mapping[str, Any]
    handler_bindings: Mapping[str, str]
    policy: Mapping[str, Any]


class ServiceRegistry:
    """Load validated service manifests from an explicit directory."""

    MANIFEST_NAME = "service.json"

    def __init__(self, root: str | Path, *, trusted_handler_ids: set[str] | frozenset[str]):
        supplied_root = Path(root).expanduser()
        if supplied_root.is_symlink():
            raise ServiceRegistryError("registry_root_symlink", "service registry root must not be a symlink")
        self.root = supplied_root.resolve()
        self.trusted_handler_ids = frozenset(trusted_handler_ids)

    def load(self, service_id: str) -> RegisteredService:
        if not isinstance(service_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", service_id):
            raise ServiceRegistryError("invalid_service_id", "service ID must be a lowercase identifier")
        services = self.load_all()
        service = services.get(service_id)
        if service is None:
            raise ServiceRegistryError("unknown_service", f"unknown service ID: {service_id}")
        return service

    def load_all(self) -> Mapping[str, RegisteredService]:
        if not self.root.exists() or not self.root.is_dir():
            raise ServiceRegistryError("registry_root_missing", "service registry root does not exist")
        loaded: dict[str, RegisteredService] = {}
        for directory in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir():
                continue
            if directory.is_symlink():
                raise ServiceRegistryError("service_directory_symlink", f"service directory is a symlink: {directory.name}")
            manifest_path = directory / self.MANIFEST_NAME
            if not manifest_path.exists():
                raise ServiceRegistryError("service_manifest_missing", f"missing {self.MANIFEST_NAME} in {directory.name}")
            if manifest_path.is_symlink():
                raise ServiceRegistryError("service_manifest_symlink", f"service manifest is a symlink: {directory.name}")
            service = self._load_manifest(directory, manifest_path)
            if service.service_id in loaded:
                raise ServiceRegistryError("duplicate_service_id", f"duplicate service ID: {service.service_id}")
            loaded[service.service_id] = service
        return MappingProxyType(loaded)

    def _resolve_file(self, directory: Path, relative: object, label: str) -> Path:
        if not isinstance(relative, str) or not relative:
            raise ServiceRegistryError("invalid_manifest_path", f"{label} path must be a non-empty relative string")
        posix = PurePosixPath(relative)
        if posix.is_absolute() or any(part in {"", ".", ".."} for part in posix.parts):
            raise ServiceRegistryError("invalid_manifest_path", f"{label} path must not escape its service directory")
        candidate = directory
        for part in posix.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise ServiceRegistryError("manifest_path_symlink", f"{label} path contains a symlink")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise ServiceRegistryError("manifest_file_missing", f"{label} file does not exist") from error
        if not resolved.is_relative_to(directory.resolve()):
            raise ServiceRegistryError("manifest_path_escape", f"{label} path escapes its service directory")
        if not resolved.is_file():
            raise ServiceRegistryError("manifest_file_invalid", f"{label} path is not a regular file")
        return resolved

    def _load_manifest(self, directory: Path, manifest_path: Path) -> RegisteredService:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ServiceRegistryError("invalid_service_manifest", f"cannot parse manifest in {directory.name}") from error
        expected_keys = {"schema_version", "service_id", "service_name", "version", "source", "handlers", "policy"}
        if not isinstance(manifest, dict) or set(manifest) != expected_keys:
            raise ServiceRegistryError("invalid_service_manifest", "manifest has missing or unknown properties")
        if manifest["schema_version"] != 1:
            raise ServiceRegistryError("unsupported_manifest_version", "service manifest schema_version must be 1")
        service_id = manifest["service_id"]
        if not isinstance(service_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", service_id):
            raise ServiceRegistryError("invalid_service_id", "manifest service_id must be a lowercase identifier")
        if not isinstance(manifest["service_name"], str) or not isinstance(manifest["version"], str):
            raise ServiceRegistryError("invalid_service_identity", "service_name and version must be strings")

        source_path = self._resolve_file(directory, manifest["source"], "source")
        if source_path.suffix != ".an":
            raise ServiceRegistryError("invalid_service_source", "service source must use the .an extension")
        try:
            ir = Parser(source_path.read_text(encoding="utf-8")).parse()
        except (OSError, UnicodeError) as error:
            raise ServiceRegistryError("invalid_service_source", "service source cannot be read") from error
        except Diagnostic as error:
            raise ServiceRegistryError("invalid_service_source", error.render()) from error
        if ir["service"]["name"] != manifest["service_name"]:
            raise ServiceRegistryError("service_name_mismatch", "manifest service_name does not match the service IR")
        if ir["service"]["version"] != manifest["version"]:
            raise ServiceRegistryError("service_version_mismatch", "manifest version does not match the service IR")

        handlers = manifest["handlers"]
        if not isinstance(handlers, dict) or any(
            not isinstance(operation, str) or not isinstance(handler_id, str) or not handler_id
            for operation, handler_id in handlers.items()
        ):
            raise ServiceRegistryError("invalid_handler_bindings", "handlers must map operation names to handler IDs")
        operation_names = {operation["name"] for operation in ir["operations"]}
        if set(handlers) != operation_names:
            raise ServiceRegistryError("handler_binding_mismatch", "handler bindings must cover every operation exactly once")
        unknown_handlers = sorted(set(handlers.values()) - self.trusted_handler_ids)
        if unknown_handlers:
            raise ServiceRegistryError("untrusted_handler_id", f"handler IDs are not host-registered: {', '.join(unknown_handlers)}")

        policy_path = self._resolve_file(directory, manifest["policy"], "policy")
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ServiceRegistryError("invalid_service_policy", "cannot parse service policy") from error
        policy_keys = {"schema_version", "default_decision", "capabilities", "effects"}
        if not isinstance(policy, dict) or set(policy) != policy_keys or policy["schema_version"] != 1:
            raise ServiceRegistryError("invalid_service_policy", "policy has an invalid schema")
        if policy["default_decision"] != "deny":
            raise ServiceRegistryError("policy_not_default_deny", "service policy must default to deny")
        for key in ("capabilities", "effects"):
            values = policy[key]
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                raise ServiceRegistryError("invalid_service_policy", f"policy {key} must be a string array")
            if len(values) != len(set(values)):
                raise ServiceRegistryError("invalid_service_policy", f"policy {key} contains duplicates")
        required_capabilities = {operation["capability"] for operation in ir["operations"]}
        required_effects = {effect for operation in ir["operations"] for effect in operation["effects"]}
        if not required_capabilities.issubset(set(policy["capabilities"])):
            raise ServiceRegistryError("policy_capability_missing", "policy omits a capability declared by service IR")
        if not required_effects.issubset(set(policy["effects"])):
            raise ServiceRegistryError("policy_effect_missing", "policy omits an effect declared by service IR")

        return RegisteredService(
            service_id=service_id,
            service_name=manifest["service_name"],
            version=manifest["version"],
            source_path=source_path,
            ir=ir,
            handler_bindings=MappingProxyType(dict(handlers)),
            policy=MappingProxyType(dict(policy)),
        )
