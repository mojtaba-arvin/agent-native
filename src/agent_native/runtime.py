"""Generic contract-driven request runtime for the E-009 vertical slice.

The runtime composes the E-001 parser/IR contract with the E-004 default-deny
capability model. Business behavior is injected through operation handlers;
routing, input binding, authorization, diagnostics, and output validation are
owned by this kernel. It contains no existing backend framework dependency.
"""

from __future__ import annotations

import copy
import math
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlsplit

from .ir import Diagnostic, Parser, validate_ir
from .security import OperationContract, PolicyEngine, RequestContext


class ConfigurationError(ValueError):
    pass


class RuntimeFault(RuntimeError):
    def __init__(self, code: str, status: int, *, detail: str | None = None):
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(detail or code)


class DomainFault(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


@dataclass(frozen=True)
class HandlerResult:
    data: Any
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)


class AuditReceipt:
    """Request-local receipt for a deferred durable audit event."""

    def __init__(self):
        self._committed = False
        self._fallback_recorded = False
        self._failed = False

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def recorded(self) -> bool:
        return self._committed or self._fallback_recorded or self._failed

    def mark_committed(self) -> None:
        self._committed = True

    def mark_fallback_recorded(self) -> None:
        self._fallback_recorded = True

    def mark_failed(self) -> None:
        \"\"\"Record that the atomic write rolled back; do not append a split audit row.\"\"\"
        self._failed = True


@dataclass(frozen=True)
class HandlerContext:
    operation: dict
    values: dict[str, Any]
    headers: dict[str, str]
    identity: RequestContext
    repository: Any
    now: int
    request_id: str
    audit_event: dict[str, Any] | None = None
    audit_receipt: AuditReceipt | None = None


@dataclass(frozen=True)
class RuntimeResponse:
    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


ERROR_STATUS = {
    "InvalidInput": 400,
    "Unauthorized": 403,
    "NotFound": 404,
    "Conflict": 409,
    "RateLimited": 429,
    "ServiceUnavailable": 503,
}


def load_service_ir(source: str) -> dict:
    try:
        ir = Parser(source).parse()
    except Diagnostic:
        raise
    validate_ir(ir)
    return ir


def _path_pattern(template: str) -> re.Pattern[str]:
    pieces = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", template)
    output = []
    for piece in pieces:
        if piece.startswith("{") and piece.endswith("}"):
            output.append(f"(?P<{piece[1:-1]}>[^/]+)")
        else:
            output.append(re.escape(piece))
    return re.compile("^" + "".join(output) + "$")


def _is_type(type_name: str, value: Any) -> bool:
    if type_name == "String":
        return isinstance(value, str)
    if type_name == "UUID":
        if not isinstance(value, str):
            return False
        try:
            uuid.UUID(value)
            return True
        except (ValueError, AttributeError):
            return False
    if type_name == "Integer":
        return type(value) is int
    if type_name == "Boolean":
        return type(value) is bool
    if type_name == "Float":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if type_name == "Bytes":
        return isinstance(value, bytes)
    return False


def _coerce_text(type_name: str, value: str) -> Any:
    if type_name == "String":
        return value
    if type_name == "UUID":
        try:
            return str(uuid.UUID(value))
        except ValueError:
            raise ValueError("invalid_uuid") from None
    if type_name == "Integer":
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            raise ValueError("invalid_integer")
        return int(value)
    if type_name == "Boolean":
        if value not in {"true", "false"}:
            raise ValueError("invalid_boolean")
        return value == "true"
    if type_name == "Float":
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("invalid_float")
        return number
    raise ValueError("unsupported_text_input_type")


def _valid_raw_encoding(value: str) -> bool:
    return re.search(r"%(?![0-9A-Fa-f]{2})", value) is None


def _validate_output(ir: dict, output_type: str, result: Any) -> bool:
    collection = re.fullmatch(r"List<([A-Za-z_][A-Za-z0-9_]*)>", output_type)
    if collection:
        return isinstance(result, list) and all(
            _validate_output(ir, collection.group(1), item) for item in result
        )
    custom = {item["name"]: item for item in ir["types"]}
    declaration = custom.get(output_type)
    if declaration is None:
        return _is_type(output_type, result)
    if not isinstance(result, dict):
        return False
    fields = declaration["fields"]
    if set(result) != {item["name"] for item in fields}:
        return False
    return all(_is_type(item["type"], result[item["name"]]) for item in fields)


def validate_operation_inputs(ir: dict, operation_name: str, values: object) -> dict[str, Any]:
    """Validate already-parsed proposal inputs against one operation's IR schema."""
    if not isinstance(values, dict):
        raise ValueError("operation_inputs_must_be_object")
    operation = next((item for item in ir["operations"] if item["name"] == operation_name), None)
    if operation is None:
        raise ValueError("unknown_operation")
    fields = {field["name"]: field["type"] for field in operation["input"]}
    if set(values) != set(fields):
        raise ValueError("operation_input_fields_mismatch")
    for field_name, type_name in fields.items():
        if not _validate_output(ir, type_name, values[field_name]):
            raise ValueError(f"invalid_input_type:{field_name}")
    for rule in operation["validation"]:
        field_name, separator, rule_name = rule.partition(".")
        if separator != "." or field_name not in values:
            raise ValueError("unsupported_validation_rule")
        if rule_name == "non_empty":
            value = values[field_name]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"invalid_input_rule:{field_name}")
        else:
            raise ValueError(f"unsupported_validation_rule:{rule_name}")
    return copy.deepcopy(values)


class ServiceRuntime:
    """Framework-owned request lifecycle with injected application handlers."""

    def __init__(
        self,
        ir: dict,
        *,
        handlers: dict[str, Callable[[HandlerContext], Any]],
        repository: Any,
        trusted_effects: set[str] | frozenset[str],
        clock: Callable[[], int] | None = None,
        audit_sink: Callable[[dict], None] | None = None,
    ):
        try:
            validate_ir(ir)
        except Diagnostic as error:
            raise ConfigurationError(f"invalid_service_ir:{error.code}") from error
        if not isinstance(trusted_effects, (set, frozenset)) or any(
            not isinstance(value, str) or not value for value in trusted_effects
        ):
            raise ConfigurationError("trusted_effects_must_be_a_string_set")
        if not isinstance(handlers, dict):
            raise ConfigurationError("operation_handlers_must_be_a_mapping")

        owned_ir = copy.deepcopy(ir)
        operations = tuple(owned_ir["operations"])
        operation_names = {item["name"] for item in operations}
        if set(handlers) != operation_names or any(not callable(item) for item in handlers.values()):
            raise ConfigurationError("handler_names_must_match_service_operations_exactly")
        for operation in operations:
            if not set(operation["effects"]).issubset(trusted_effects):
                raise ConfigurationError(f"untrusted_effect_in_service_contract:{operation['name']}")

        self._ir = owned_ir
        self._operations = tuple(
            (copy.deepcopy(item), _path_pattern(item["path"]))
            for item in operations
        )
        self._handlers = MappingProxyType(dict(handlers))
        self.repository = repository
        self.trusted_effects = frozenset(trusted_effects)
        self.policy = PolicyEngine()
        self.clock = clock or (lambda: int(time.time()))
        self.audit_sink = audit_sink
        self._contracts = {
            item["name"]: OperationContract(
                name=item["name"],
                required_capability=item["capability"],
                allowed_effects=frozenset(item["effects"]),
            )
            for item in operations
        }

    @property
    def ir(self) -> dict:
        """Return a defensive copy; callers cannot mutate the active contract."""
        return copy.deepcopy(self._ir)

    @property
    def operations(self) -> tuple[dict, ...]:
        """Return defensive operation copies for inspection and diagnostics."""
        return tuple(copy.deepcopy(operation) for operation, _pattern in self._operations)

    @property
    def handlers(self):
        """Read-only view of the registered trusted handler mapping."""
        return self._handlers

    def _route(self, method: str, path: str) -> tuple[dict, dict[str, str]]:
        matches = []
        for operation, pattern in self._operations:
            match = pattern.fullmatch(path)
            if match:
                matches.append((operation, match.groupdict()))
                if operation["method"] == method:
                    return operation, match.groupdict()
        if matches:
            raise RuntimeFault("METHOD_NOT_ALLOWED", 405)
        raise RuntimeFault("ROUTE_NOT_FOUND", 404)

    @staticmethod
    def _headers(headers: dict[str, str] | None) -> dict[str, str]:
        result = {}
        for key, value in (headers or {}).items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise RuntimeFault("INVALID_HEADERS", 400)
            normalized = key.lower()
            if normalized in result:
                raise RuntimeFault("INVALID_HEADERS", 400)
            result[normalized] = value
        return result

    @staticmethod
    def _query_values(raw_query: str) -> dict[str, str]:
        if not _valid_raw_encoding(raw_query):
            raise RuntimeFault("InvalidInput", 400)
        try:
            pairs = parse_qsl(
                raw_query,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
            )
        except (ValueError, UnicodeDecodeError):
            raise RuntimeFault("InvalidInput", 400) from None
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeFault("InvalidInput", 400)
            result[key] = value
        return result

    def _bind_inputs(
        self,
        operation: dict,
        path_values: dict[str, str],
        query: dict[str, str],
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        fields = operation["input"]
        expected_query = {item["name"] for item in fields if item["source"] == "query"}
        expected_body = {item["name"] for item in fields if item["source"] == "body"}
        if set(query) - expected_query or set(body) != expected_body:
            raise RuntimeFault("InvalidInput", 400)

        values = {}
        for item in fields:
            name, source, type_name = item["name"], item["source"], item["type"]
            if source == "path":
                raw = path_values.get(name)
            elif source == "query":
                raw = query.get(name)
            elif source == "header":
                raw = headers.get(name.lower().replace("_", "-"))
            elif source == "body":
                raw = None
                value = body.get(name)
            else:
                raise RuntimeFault("UNSUPPORTED_INPUT_SOURCE", 500)

            if source in {"path", "query", "header"}:
                try:
                    value = _coerce_text(type_name, raw) if raw is not None else None
                except (ValueError, OverflowError):
                    raise RuntimeFault("InvalidInput", 400, detail=name) from None
            if not _is_type(type_name, value):
                raise RuntimeFault("InvalidInput", 400, detail=name)
            values[name] = value

        for rule in operation["validation"]:
            field_name, separator, rule_name = rule.partition(".")
            if separator != "." or field_name not in values:
                raise RuntimeFault("UNSUPPORTED_VALIDATION_RULE", 500)
            if rule_name == "non_empty":
                value = values[field_name]
                if not isinstance(value, str) or not value.strip():
                    raise RuntimeFault("InvalidInput", 400, detail=field_name)
            else:
                raise RuntimeFault("UNSUPPORTED_VALIDATION_RULE", 500)
        return values

    def dispatch(
        self,
        method: str,
        target: str,
        body: dict[str, Any],
        identity: RequestContext | None,
        *,
        headers: dict[str, str] | None = None,
        request_id: str | None = None,
    ) -> RuntimeResponse:
        request_id = request_id or str(uuid.uuid4())
        deferred_audit_event = None
        deferred_audit_receipt = None
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
            request_id = str(uuid.uuid4())
        if not isinstance(method, str) or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return RuntimeResponse(405, {"error": {"code": "METHOD_NOT_ALLOWED"}, "request_id": request_id})
        if not isinstance(body, dict):
            return RuntimeResponse(400, {"error": {"code": "InvalidInput"}, "request_id": request_id})
        if not isinstance(identity, RequestContext):
            return RuntimeResponse(401, {"error": {"code": "UNAUTHENTICATED"}, "request_id": request_id})

        try:
            try:
                parsed = urlsplit(target)
            except ValueError:
                raise RuntimeFault("InvalidInput", 400) from None
            raw_path = parsed.path
            if (
                parsed.scheme or parsed.netloc or parsed.fragment
                or not raw_path.startswith("/")
                or not _valid_raw_encoding(raw_path)
                or re.search(r"%(?:2f|5c)", raw_path, re.IGNORECASE)
            ):
                raise RuntimeFault("InvalidInput", 400)
            try:
                path = unquote(raw_path, encoding="utf-8", errors="strict")
            except UnicodeDecodeError:
                raise RuntimeFault("InvalidInput", 400) from None
            if (
                not path.startswith("/")
                or "//" in path
                or any(ord(char) < 0x20 or ord(char) == 0x7F for char in path)
            ):
                raise RuntimeFault("InvalidInput", 400)
            operation, path_values = self._route(method, path)
            normalized_headers = self._headers(headers)
            query_values = self._query_values(parsed.query)

            now = self.clock()
            if type(now) is not int or now < 0:
                raise RuntimeFault("CLOCK_UNAVAILABLE", 503)
            trusted_identity = RequestContext(
                principal_id=identity.principal_id,
                tenant_id=identity.tenant_id,
                now=now,
                grants=identity.grants,
            )
            effects = frozenset(operation["effects"])
            decision = self.policy.authorize(
                self._contracts[operation["name"]],
                resource=path,
                requested_effects=effects,
                context=trusted_identity,
            )
            audit_event = {
                **decision.audit_event,
                "request_id": request_id,
                "timestamp": now,
            }
            defer_audit = bool(
                self.audit_sink is not None
                and decision.allowed
                and bool(effects.intersection({"queue.submit", "repository.write", "event.publish"}))
                and callable(getattr(self.audit_sink, "write_in_transaction", None))
            )
            if self.audit_sink is not None and not defer_audit:
                try:
                    self.audit_sink(audit_event)
                except Exception:
                    raise RuntimeFault("AUDIT_UNAVAILABLE", 503) from None
            if not decision.allowed:
                raise RuntimeFault("Unauthorized", 403, detail=decision.reason_code)
            if defer_audit:
                deferred_audit_event = audit_event
                deferred_audit_receipt = AuditReceipt()

            values = self._bind_inputs(
                operation,
                path_values,
                query_values,
                body,
                normalized_headers,
            )
            context = HandlerContext(
                operation=copy.deepcopy(operation),
                values=values,
                headers=normalized_headers,
                identity=trusted_identity,
                repository=self.repository,
                now=now,
                request_id=request_id,
                audit_event=audit_event if defer_audit else None,
                audit_receipt=deferred_audit_receipt,
            )
            try:
                result = self._handlers[operation["name"]](context)
            except DomainFault as error:
                if error.code not in operation["errors"]:
                    raise RuntimeFault("HANDLER_CONTRACT_VIOLATION", 500) from None
                raise RuntimeFault(error.code, ERROR_STATUS.get(error.code, 500), detail=error.detail) from None

            if defer_audit and not deferred_audit_receipt.committed:
                raise RuntimeFault("AUDIT_ATOMIC_COMMIT_REQUIRED", 503)
            if isinstance(result, HandlerResult):
                data, status_code, response_headers = result.data, result.status_code, result.headers
            else:
                data, status_code, response_headers = result, 200, {}
            if status_code not in {200, 201, 202, 204}:
                raise RuntimeFault("INVALID_HANDLER_STATUS", 500)
            if status_code == 204:
                if data is not None:
                    raise RuntimeFault("INVALID_HANDLER_RESULT", 500)
            elif not _validate_output(self._ir, operation["output"], data):
                raise RuntimeFault("INVALID_HANDLER_RESULT", 500)
            for key, value in response_headers.items():
                if (
                    not isinstance(key, str) or not isinstance(value, str)
                    or "\r" in key or "\n" in key or "\r" in value or "\n" in value
                ):
                    raise RuntimeFault("INVALID_HANDLER_HEADERS", 500)
            payload = {"data": data, "request_id": request_id}
            return RuntimeResponse(status_code, payload, dict(response_headers))
        except RuntimeFault as error:
            if deferred_audit_event is not None and not deferred_audit_receipt.recorded:
                try:
                    self.audit_sink(deferred_audit_event)
                    deferred_audit_receipt.mark_fallback_recorded()
                except Exception:
                    return RuntimeResponse(
                        503,
                        {"error": {"code": "AUDIT_UNAVAILABLE"}, "request_id": request_id},
                    )
            payload = {"error": {"code": error.code}, "request_id": request_id}
            return RuntimeResponse(error.status, payload)
        except (ValueError, TypeError, KeyError, AttributeError):
            if deferred_audit_event is not None and not deferred_audit_receipt.recorded:
                try:
                    self.audit_sink(deferred_audit_event)
                    deferred_audit_receipt.mark_fallback_recorded()
                except Exception:
                    return RuntimeResponse(
                        503,
                        {"error": {"code": "AUDIT_UNAVAILABLE"}, "request_id": request_id},
                    )
            return RuntimeResponse(
                500,
                {"error": {"code": "INTERNAL_ERROR"}, "request_id": request_id},
            )
        except Exception:
            if deferred_audit_event is not None and not deferred_audit_receipt.recorded:
                try:
                    self.audit_sink(deferred_audit_event)
                    deferred_audit_receipt.mark_fallback_recorded()
                except Exception:
                    return RuntimeResponse(
                        503,
                        {"error": {"code": "AUDIT_UNAVAILABLE"}, "request_id": request_id},
                    )
            return RuntimeResponse(
                500,
                {"error": {"code": "INTERNAL_ERROR"}, "request_id": request_id},
            )


@dataclass(frozen=True)
class RuntimeSnapshot:
    """One immutable publication record captured once per request."""

    revision: int
    runtime: ServiceRuntime


class RuntimeRegistry:
    """Atomically publish fully constructed runtime snapshots.

    A request obtains one snapshot and uses that runtime for its complete
    lifecycle. Publication never mutates a live runtime in place.
    """

    def __init__(self, runtime: ServiceRuntime, *, revision: int = 1):
        if not isinstance(runtime, ServiceRuntime):
            raise ConfigurationError("runtime_snapshot_requires_service_runtime")
        if type(revision) is not int or revision < 1:
            raise ConfigurationError("runtime_revision_must_be_positive_integer")
        self._lock = threading.Lock()
        self._snapshot = RuntimeSnapshot(revision=revision, runtime=runtime)

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return self._snapshot

    def publish(self, runtime: ServiceRuntime, *, revision: int) -> RuntimeSnapshot:
        if not isinstance(runtime, ServiceRuntime):
            raise ConfigurationError("runtime_snapshot_requires_service_runtime")
        if type(revision) is not int or revision < 1:
            raise ConfigurationError("runtime_revision_must_be_positive_integer")
        with self._lock:
            if revision <= self._snapshot.revision:
                raise ConfigurationError("runtime_revision_must_increase")
            snapshot = RuntimeSnapshot(revision=revision, runtime=runtime)
            self._snapshot = snapshot
            return snapshot
