"""Disposable E-001 parser prototype; not production framework code."""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TOKEN = re.compile(
    r'(?P<space>\s+)|(?P<comment>//[^\n]*)|(?P<string>"(?:\\.|[^"\\])*")|'
    r'(?P<ident>[A-Za-z_][A-Za-z0-9_.-]*)|(?P<punct>[{}:;\[\],])'
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    column: int


class Diagnostic(Exception):
    def __init__(self, code: str, message: str, token: Token):
        super().__init__(message)
        self.code, self.message, self.token = code, message, token

    def render(self) -> str:
        return (f"{self.token.line}:{self.token.column}: {self.code}: "
                f"{self.message}")


def lex(source: str) -> list[Token]:
    result: list[Token] = []
    offset = 0
    line = column = 1
    while offset < len(source):
        match = TOKEN.match(source, offset)
        if not match:
            bad = Token("invalid", source[offset], line, column)
            raise Diagnostic("AN001", f"unexpected character {source[offset]!r}", bad)
        value = match.group()
        kind = match.lastgroup or ""
        if kind not in ("space", "comment"):
            result.append(Token(kind, value, line, column))
        lines = value.splitlines(keepends=True)
        if len(lines) > 1:
            line += len(lines) - 1
            column = len(lines[-1]) + 1
        else:
            column += len(value)
        offset = match.end()
    result.append(Token("eof", "", line, column))
    return result


class Parser:
    def __init__(self, source: str):
        self.tokens = lex(source)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def fail(self, code: str, message: str) -> None:
        raise Diagnostic(code, message, self.current)

    def take(self, value: str | None = None, kind: str | None = None) -> Token:
        token = self.current
        if value is not None and token.value != value:
            self.fail("AN002", f"expected {value!r}, found {token.value!r}")
        if kind is not None and token.kind != kind:
            self.fail("AN003", f"expected {kind}, found {token.kind}")
        self.index += 1
        return token

    def identifier(self) -> str:
        return self.take(kind="ident").value

    def string(self) -> str:
        token = self.take(kind="string")
        return json.loads(token.value)

    def name_value(self, keyword: str) -> str:
        self.take(keyword)
        self.take(":")
        value = self.identifier()
        self.take(";")
        return value

    def string_value(self, keyword: str) -> str:
        self.take(keyword)
        self.take(":")
        value = self.string()
        self.take(";")
        return value

    def list_value(self, keyword: str) -> list[str]:
        self.take(keyword)
        self.take(":")
        self.take("[")
        values: list[str] = []
        if self.current.value != "]":
            values.append(self.identifier())
            while self.current.value == ",":
                self.take(",")
                values.append(self.identifier())
        self.take("]")
        self.take(";")
        if len(values) != len(set(values)):
            self.fail("AN004", f"{keyword} contains duplicate entries")
        return values

    def parse(self) -> dict:
        self.take("service")
        name = self.identifier()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            self.fail("AN014", f"invalid service identifier {name!r}")
        self.take("{")
        version = self.string_value("version")
        types = []
        type_names: set[str] = set()
        while self.current.value == "type":
            item_type = self.type_decl()
            if item_type["name"] in type_names:
                self.fail("AN016", f"duplicate type {item_type['name']!r}")
            type_names.add(item_type["name"])
            types.append(item_type)
        operations = []
        names: set[str] = set()
        while self.current.value == "operation":
            operation = self.operation()
            if operation["name"] in names:
                self.fail("AN005", f"duplicate operation {operation['name']!r}")
            names.add(operation["name"])
            operations.append(operation)
        self.take("}")
        if self.current.kind != "eof":
            self.fail("AN006", "unexpected content after service declaration")
        if not operations:
            self.fail("AN007", "service must declare at least one operation")
        known_types = {"String", "UUID", "Integer", "Boolean", "Bytes", "Float"} | type_names
        for item_type in types:
            for field in item_type["fields"]:
                if field["type"] not in known_types:
                    self.fail("AN020", f"unknown type {field['type']!r} in record field {field['name']!r}")
        for operation in operations:
            if operation["output"] not in known_types:
                self.fail("AN020", f"unknown output type {operation['output']!r}")
            for field in operation["input"]:
                if field["type"] not in known_types:
                    self.fail("AN020", f"unknown input type {field['type']!r} in field {field['name']!r}")
        ir = {
            "ir_version": 1,
            "service": {"name": name, "version": version},
            "types": sorted(types, key=lambda item: item["name"]),
            "operations": sorted(operations, key=lambda item: item["name"]),
        }
        validate_ir(ir)
        return ir

    def type_decl(self) -> dict:
        self.take("type")
        name = self.identifier()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            self.fail("AN017", f"invalid type identifier {name!r}")
        self.take("{")
        fields = []
        field_names: set[str] = set()
        while self.current.value != "}":
            field = self.identifier()
            if field in field_names:
                self.fail("AN018", f"duplicate type field {field!r}")
            field_names.add(field)
            self.take(":")
            type_name = self.identifier()
            self.take(";")
            fields.append({"name": field, "type": type_name})
        self.take("}")
        if not fields:
            self.fail("AN019", f"type {name!r} must declare at least one field")
        return {"name": name, "fields": sorted(fields, key=lambda item: item["name"])}

    def operation(self) -> dict:
        self.take("operation")
        name = self.identifier()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            self.fail("AN015", f"invalid operation identifier {name!r}")
        self.take("{")
        method = self.name_value("method")
        path = self.string_value("path")
        self.take("input")
        self.take("{")
        inputs = []
        input_names: set[str] = set()
        while self.current.value != "}":
            field = self.identifier()
            if field in input_names:
                self.fail("AN008", f"duplicate input field {field!r}")
            input_names.add(field)
            self.take(":")
            type_name = self.identifier()
            self.take("from")
            source = self.identifier()
            if source not in {"path", "query", "body", "header"}:
                self.fail("AN009", f"unsupported input source {source!r}")
            self.take(";")
            inputs.append({"name": field, "type": type_name, "source": source})
        self.take("}")
        output = self.name_value("output")
        errors = self.list_value("errors")
        validation = self.list_value("validation")
        effects = self.list_value("effects")
        capability = self.string_value("capability")
        self.take("}")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            self.fail("AN010", f"unsupported HTTP method {method!r}")
        if not path.startswith("/"):
            self.fail("AN011", "path must start with '/'")
        placeholders = re.findall(r"\{([^{}]+)\}", path)
        if path.count("{") != len(placeholders) or path.count("}") != len(placeholders):
            self.fail("AN012", "path contains malformed parameter braces")
        if len(placeholders) != len(set(placeholders)):
            self.fail("AN012", "path contains a duplicate parameter")
        path_inputs = {item["name"] for item in inputs if item["source"] == "path"}
        if set(placeholders) != path_inputs:
            self.fail("AN013", "path parameters must match path-sourced input fields exactly")
        return {
            "name": name,
            "method": method,
            "path": path,
            "input": sorted(inputs, key=lambda item: item["name"]),
            "output": output,
            "errors": sorted(errors),
            "validation": sorted(validation),
            "effects": sorted(effects),
            "capability": capability,
        }



BUILTIN_TYPES = frozenset({"String", "UUID", "Integer", "Boolean", "Bytes", "Float"})


def validate_ir(ir: object) -> None:
    """Validate untrusted structured IR using the same invariants as the text parser."""
    token = Token("invalid", "", 1, 1)

    def fail(code: str, message: str) -> None:
        raise Diagnostic(code, message, token)

    if not isinstance(ir, dict) or set(ir) != {"ir_version", "service", "types", "operations"} or ir.get("ir_version") != 1:
        fail("AN021", "unsupported or malformed IR version or top-level shape")
    service = ir.get("service")
    if not isinstance(service, dict) or set(service) != {"name", "version"} or not isinstance(service.get("name"), str) or not isinstance(service.get("version"), str) or not service["version"]:
        fail("AN022", "service identity and version are required")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", service["name"]):
        fail("AN014", "invalid service identifier")
    types = ir.get("types")
    operations = ir.get("operations")
    if not isinstance(types, list) or not isinstance(operations, list) or not operations:
        fail("AN023", "types and non-empty operations arrays are required")

    type_names: set[str] = set()
    for item_type in types:
        if not isinstance(item_type, dict) or not isinstance(item_type.get("name"), str):
            fail("AN024", "malformed type declaration")
        name = item_type["name"]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            fail("AN017", f"invalid type identifier {name!r}")
        if name in BUILTIN_TYPES or name in type_names:
            fail("AN016", f"duplicate or reserved type {name!r}")
        type_names.add(name)

    known_types = BUILTIN_TYPES | type_names
    for item_type in types:
        fields = item_type.get("fields")
        if set(item_type) != {"name", "fields"} or not isinstance(fields, list) or not fields:
            fail("AN019", f"type {item_type['name']!r} must declare fields")
        field_names: set[str] = set()
        for field in fields:
            if not isinstance(field, dict) or set(field) != {"name", "type"} or not isinstance(field.get("name"), str):
                fail("AN025", f"malformed field in type {item_type['name']!r}")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field["name"]):
                fail("AN034", f"invalid field identifier {field['name']!r}")
            if field["name"] in field_names:
                fail("AN018", f"duplicate type field {field['name']!r}")
            field_names.add(field["name"])
            if not isinstance(field.get("type"), str) or field.get("type") not in known_types:
                fail("AN020", f"unknown type {field.get('type')!r} in record field {field['name']!r}")

    operation_names: set[str] = set()
    route_keys: set[tuple[str, str]] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            fail("AN026", "malformed operation declaration")
        name = operation.get("name")
        if set(operation) != {"name", "method", "path", "input", "output", "errors", "validation", "effects", "capability"}:
            fail("AN026", "operation contains missing or unknown properties")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name in operation_names:
            fail("AN005", f"invalid or duplicate operation {name!r}")
        operation_names.add(name)
        method = operation.get("method")
        path = operation.get("path")
        if not isinstance(method, str) or method not in {"GET", "POST"}:
            fail("AN003", f"unsupported method {method!r}")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or "?" in path
            or "#" in path
            or "//" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            fail("AN027", f"invalid route path {path!r}")
        route_key = (method, path)
        if route_key in route_keys:
            fail("AN028", f"duplicate route {method} {path}")
        route_keys.add(route_key)
        if not isinstance(operation.get("output"), str) or operation.get("output") not in known_types:
            fail("AN020", f"unknown output type {operation.get('output')!r}")
        capability = operation.get("capability")
        if not isinstance(capability, str) or not capability:
            fail("AN029", f"operation {name!r} requires a capability")
        inputs = operation.get("input")
        if not isinstance(inputs, list):
            fail("AN030", f"operation {name!r} input must be an array")
        input_names: set[str] = set()
        for field in inputs:
            if not isinstance(field, dict) or set(field) != {"name", "type", "source"} or not isinstance(field.get("name"), str):
                fail("AN031", f"malformed input field in {name!r}")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field["name"]):
                fail("AN034", f"invalid input identifier {field['name']!r}")
            if field["name"] in input_names:
                fail("AN008", f"duplicate input field {field['name']!r}")
            input_names.add(field["name"])
            if not isinstance(field.get("type"), str) or field.get("type") not in known_types:
                fail("AN020", f"unknown input type {field.get('type')!r}")
            source = field.get("source")
            if not isinstance(source, str) or source not in {"path", "body", "query"}:
                fail("AN010", f"unsupported input source {source!r}")
        path_variables = re.findall(r"\\{([A-Za-z_][A-Za-z0-9_]*)\\}", path)
        if "{" in re.sub(r"\\{[A-Za-z_][A-Za-z0-9_]*\\}", "", path) or "}" in re.sub(r"\\{[A-Za-z_][A-Za-z0-9_]*\\}", "", path):
            fail("AN027", f"malformed path parameter in {path!r}")
        path_inputs = {field["name"] for field in inputs if field["source"] == "path"}
        if len(path_variables) != len(set(path_variables)) or set(path_variables) != path_inputs:
            fail("AN035", f"path parameters and path inputs do not match for {name!r}")
        if method == "GET" and any(field["source"] == "body" for field in inputs):
            fail("AN037", f"GET operation {name!r} cannot declare body inputs")
        for key in ("errors", "validation", "effects"):
            values = operation.get(key)
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                fail("AN032", f"operation {name!r} requires a string array for {key}")
            if len(values) != len(set(values)):
                fail("AN004", f"duplicate value in {key} for operation {name!r}")
        input_types = {field["name"]: field["type"] for field in inputs}
        for rule in operation["validation"]:
            field_name, separator, rule_name = rule.partition(".")
            if separator != "." or rule_name != "non_empty" or input_types.get(field_name) != "String":
                fail("AN036", f"unsupported or unbound validation rule {rule!r}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: agent_native.py <service.an>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        ir = Parser(path.read_text(encoding="utf-8")).parse()
    except (OSError, UnicodeError) as exc:
        print(f"IO001: {exc}", file=sys.stderr)
        return 2
    except Diagnostic as exc:
        print(exc.render(), file=sys.stderr)
        return 1
    print(json.dumps(ir, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
