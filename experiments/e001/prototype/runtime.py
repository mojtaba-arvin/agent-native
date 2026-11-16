from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from agent_native import Parser

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPOSITORY_ROOT / "experiments" / "e004"))
from security_model import OperationContract, PolicyEngine, RequestContext  # noqa: E402


class RuntimeFault(Exception):
    def __init__(self, code: str, *, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(detail or code)


class ReferenceRuntime:
    """Disposable executor for the fixed E-001 catalog task; not a product runtime."""

    def __init__(self, ir: dict, *, trusted_effects: set[str] | frozenset[str]):
        self.ir = ir
        self.operations = tuple(ir["operations"])
        self.trusted_effects = frozenset(trusted_effects)
        self.policy = PolicyEngine()
        self.items: dict[str, dict[str, str]] = {}
        self.next_id = 0

    @classmethod
    def from_source(cls, source: str, *, trusted_effects: set[str] | frozenset[str]):
        return cls(Parser(source).parse(), trusted_effects=trusted_effects)

    @staticmethod
    def _path_pattern(template: str) -> re.Pattern[str]:
        parts = re.split(r"(\{[A-Za-z_][A-Za-z0-9_]*\})", template)
        expression = []
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                name = part[1:-1]
                expression.append(f"(?P<{name}>[^/]+)")
            else:
                expression.append(re.escape(part))
        return re.compile("^" + "".join(expression) + "$")

    def _resolve(self, method: str, path: str):
        path_matches = []
        for operation in self.operations:
            match = self._path_pattern(operation["path"]).fullmatch(path)
            if match:
                path_matches.append((operation, match.groupdict()))
                if operation["method"] == method:
                    return operation, match.groupdict()
        if path_matches:
            raise RuntimeFault("METHOD_NOT_ALLOWED")
        raise RuntimeFault("ROUTE_NOT_FOUND")

    @staticmethod
    def _valid_value(type_name: str, value: object) -> bool:
        if type_name == "String":
            return isinstance(value, str)
        if type_name == "UUID":
            if not isinstance(value, str):
                return False
            try:
                uuid.UUID(value)
                return True
            except ValueError:
                return False
        if type_name == "Integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if type_name == "Boolean":
            return isinstance(value, bool)
        if type_name == "Float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if type_name == "Bytes":
            return isinstance(value, bytes)
        return False

    def _fault(self, operation: dict, declared_error: str, *, detail: str | None = None):
        if declared_error not in operation["errors"]:
            raise RuntimeFault("UNDECLARED_ERROR", detail=declared_error)
        raise RuntimeFault(declared_error, detail=detail)

    def dispatch(
        self,
        method: str,
        target: str,
        body: dict[str, object],
        context: RequestContext,
    ) -> dict[str, str]:
        parsed = urlsplit(target)
        path = parsed.path
        operation, path_values = self._resolve(method, path)

        effects = frozenset(operation["effects"])
        if not effects.issubset(self.trusted_effects):
            raise RuntimeFault("UNTRUSTED_EFFECT")

        contract = OperationContract(
            name=operation["name"],
            required_capability=operation["capability"],
            allowed_effects=effects,
        )
        decision = self.policy.authorize(
            contract,
            resource=path,
            requested_effects=effects,
            context=context,
        )
        if not decision.allowed:
            self._fault(operation, "Unauthorized", detail=decision.reason_code)

        query_values = parse_qs(parsed.query, keep_blank_values=True)
        values: dict[str, object] = {}
        for field in operation["input"]:
            source = field["source"]
            if source == "path":
                value = path_values.get(field["name"])
            elif source == "body":
                value = body.get(field["name"])
            elif source == "query":
                candidates = query_values.get(field["name"], [])
                value = candidates[0] if candidates else None
            else:
                raise RuntimeFault("UNSUPPORTED_INPUT_SOURCE")
            if not self._valid_value(field["type"], value):
                self._fault(operation, "InvalidInput", detail=field["name"])
            values[field["name"]] = value

        for rule in operation["validation"]:
            if rule == "name.non_empty" and not str(values.get("name", "")).strip():
                self._fault(operation, "InvalidInput", detail="name")

        if operation["name"] == "create_item":
            self.next_id += 1
            item_id = str(uuid.UUID(int=self.next_id))
            item = {"id": item_id, "name": str(values["name"])}
            self.items[item_id] = item
            return dict(item)

        if operation["name"] == "get_item":
            item = self.items.get(str(values["id"]))
            if item is None:
                self._fault(operation, "NotFound", detail="item")
            return dict(item)

        raise RuntimeFault("UNIMPLEMENTED_OPERATION", detail=operation["name"])
