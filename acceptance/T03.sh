#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import json
from pathlib import Path
import sys

schema_path = Path("schemas/service-ir-v1.schema.json")
compatibility_path = Path("docs/IR_V1.md")
validator_path = Path("src/agent_native/ir.py")
test_path = Path("tests/test_ir_v1_contract.py")

required_files = {
    "versioned JSON Schema": schema_path,
    "compatibility and evolution contract": compatibility_path,
    "executable validator": validator_path,
    "contract regression suite": test_path,
}
missing = [name for name, path in required_files.items() if not path.is_file()]
if missing:
    print("T03 acceptance: missing v1 IR contract outputs:")
    for name in missing:
        print(f"- {name}")
    sys.exit(1)

schema = json.loads(schema_path.read_text(encoding="utf-8"))
if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
    raise SystemExit("T03 acceptance: schema must declare JSON Schema Draft 2020-12.")
if schema.get("$id") != "https://agent-native.dev/schemas/service-ir-v1.schema.json":
    raise SystemExit("T03 acceptance: schema $id is not the frozen v1 identifier.")
if schema.get("properties", {}).get("ir_version", {}).get("const") != 1:
    raise SystemExit("T03 acceptance: ir_version must be exactly integer 1.")
if schema.get("additionalProperties") is not False:
    raise SystemExit("T03 acceptance: unknown top-level properties must be rejected.")
required = {"ir_version", "service", "types", "operations"}
if set(schema.get("required", [])) != required:
    raise SystemExit("T03 acceptance: the canonical top-level shape changed.")

compatibility = compatibility_path.read_text(encoding="utf-8")
markers = (
    "# Agent Native Service IR v1",
    "complete snapshot",
    "not a patch",
    "unknown or unsupported versions",
    "fail closed",
    "ir_version",
    "service-manifest",
    "explicit migration",
    "additionalProperties",
)
missing_markers = [marker for marker in markers if marker not in compatibility]
if missing_markers:
    print("T03 acceptance: compatibility contract is incomplete:")
    for marker in missing_markers:
        print(f"- {marker}")
    sys.exit(1)

validator = validator_path.read_text(encoding="utf-8")
if "def validate_ir(ir: object)" not in validator:
    raise SystemExit("T03 acceptance: canonical executable validate_ir() API is missing.")

print("T03 acceptance: the frozen schema, compatibility rules, and executable validator are present.")
PY

PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_ir_v1_contract.py' -v
