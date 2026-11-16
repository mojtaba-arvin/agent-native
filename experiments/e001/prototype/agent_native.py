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
        return {
            "ir_version": 1,
            "service": {"name": name, "version": version},
            "types": sorted(types, key=lambda item: item["name"]),
            "operations": sorted(operations, key=lambda item: item["name"]),
        }

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
