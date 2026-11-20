"""Deterministic PostgreSQL schema plans derived from validated service IR."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_TYPE_MAP = {
    "String": ("TEXT", str),
    "UUID": ("UUID", str),
    "Integer": ("BIGINT", int),
    "Boolean": ("BOOLEAN", bool),
    "Float": ("DOUBLE PRECISION", (int, float)),
    "Bytes": ("BYTEA", bytes),
}


class MigrationError(ValueError):
    """A service IR cannot be represented as a safe additive SQL migration."""


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    sql_type: str
    python_type: type | tuple[type, ...]


@dataclass(frozen=True)
class ResourceSpec:
    name: str
    key: str
    generated_key: bool
    columns: tuple[ColumnSpec, ...]
    create_fields: tuple[str, ...]
    unique_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class MigrationPlan:
    service_id: str
    service_version: str
    checksum: str
    resources: tuple[ResourceSpec, ...]


class IRMigrationPlanner:
    """Compile the resource type declarations referenced by CRUD create handlers.

    The validated IR owns field names and scalar types. The host-owned handler
    binding supplies the physical resource name and create-input projection.
    """

    @classmethod
    def from_service(cls, service: Any) -> MigrationPlan:
        service_id = getattr(service, "service_id", None)
        service_version = getattr(service, "version", None)
        ir = getattr(service, "ir", None)
        bindings = getattr(service, "handler_bindings", None)
        configs = getattr(service, "handler_configs", None)
        if (
            not isinstance(service_id, str) or not _IDENTIFIER.fullmatch(service_id)
            or not isinstance(service_version, str) or not service_version.strip()
            or not isinstance(ir, Mapping) or not isinstance(bindings, Mapping)
            or not isinstance(configs, Mapping)
        ):
            raise MigrationError("invalid_registered_service")
        if ir.get("ir_version") != 1:
            raise MigrationError("unsupported_ir_version")

        declarations = {
            item["name"]: item for item in ir.get("types", ())
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        }
        resources: dict[str, ResourceSpec] = {}
        reserved = {"schema_migrations", "idempotency_keys", "audit_log", "outbox"}
        for operation in ir.get("operations", ()):
            name = operation.get("name")
            if bindings.get(name) != "crud.create":
                continue
            config = configs.get(name, {})
            resource = config.get("resource")
            if not isinstance(resource, str) or not _IDENTIFIER.fullmatch(resource) or resource in reserved:
                raise MigrationError("invalid_resource_identifier")
            output = operation.get("output")
            if not isinstance(output, str) or output not in declarations:
                raise MigrationError("crud_create_requires_record_output_type")
            fields = declarations[output].get("fields")
            if not isinstance(fields, (list, tuple)) or not fields:
                raise MigrationError("resource_type_requires_fields")
            columns = []
            names = set()
            for field in fields:
                field_name, type_name = field.get("name"), field.get("type")
                if not isinstance(field_name, str) or not _IDENTIFIER.fullmatch(field_name) or field_name == "tenant_id":
                    raise MigrationError("invalid_ir_field_identifier")
                if field_name in names:
                    raise MigrationError("duplicate_ir_field")
                names.add(field_name)
                mapped = _TYPE_MAP.get(type_name)
                if mapped is None:
                    raise MigrationError("unsupported_ir_storage_type:" + str(type_name))
                columns.append(ColumnSpec(field_name, mapped[0], mapped[1]))
            create_fields = config.get("input_fields")
            if not isinstance(create_fields, (list, tuple)) or any(
                not isinstance(field, str) or field not in names for field in create_fields
            ) or len(create_fields) != len(set(create_fields)):
                raise MigrationError("invalid_create_input_projection")
            key = config.get("primary_key", "id" if "id" in names else create_fields[0] if create_fields else "")
            if not isinstance(key, str) or key not in names:
                raise MigrationError("invalid_primary_key_projection")
            generated_key = key not in create_fields
            if generated_key and next(column for column in columns if column.name == key).sql_type != "UUID":
                raise MigrationError("generated_primary_key_must_be_uuid")
            unique_fields = config.get("unique_fields", ())
            if not isinstance(unique_fields, (list, tuple)) or any(
                not isinstance(field, str) or field not in names or field == key
                for field in unique_fields
            ) or len(unique_fields) != len(set(unique_fields)):
                raise MigrationError("invalid_unique_field_projection")
            spec = ResourceSpec(
                name=resource,
                key=key,
                generated_key=generated_key,
                columns=tuple(columns),
                create_fields=tuple(create_fields),
                unique_fields=tuple(unique_fields),
            )
            previous = resources.get(resource)
            if previous is not None and previous != spec:
                raise MigrationError("resource_schema_conflict:" + resource)
            resources[resource] = spec

        if not resources:
            raise MigrationError("service_ir_has_no_crud_resources")
        fingerprint = {
            "service_id": service_id,
            "service_version": service_version,
            "ir": ir,
            "bindings": dict(bindings),
            "configs": {key: dict(value) for key, value in configs.items()},
        }
        canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return MigrationPlan(
            service_id=service_id,
            service_version=service_version,
            checksum=checksum,
            resources=tuple(resources[key] for key in sorted(resources)),
        )
