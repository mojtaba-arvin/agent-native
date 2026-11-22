#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import json
import tomllib
from pathlib import Path

config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
package_data = config["tool"]["setuptools"]["package-data"]["agent_native"]
if "schemas/*.json" not in package_data:
    raise SystemExit("T33 acceptance: schema JSON resources are not packaged")
schema_dir = Path("src/agent_native/schemas")
expected = {
    "gateway-plan-v1.schema.json",
    "gateway-proposal-v1.schema.json",
    "gateway-validation-v1.schema.json",
    "service-ir-v1.schema.json",
    "service-manifest-v1.schema.json",
    "service-manifest-v2.schema.json",
}
actual = {path.name for path in schema_dir.glob("*.schema.json")}
if actual != expected:
    raise SystemExit(f"T33 acceptance: packaged schema set mismatch: {sorted(actual)}")
for path in sorted(schema_dir.glob("*.schema.json")):
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise SystemExit(f"T33 acceptance: invalid packaged schema: {path}")
print("T33 acceptance: all published Draft 2020-12 schemas are packaged and parseable.")
PY
python3 -m pip install --no-deps --no-build-isolation .
python3 -m unittest discover -s tests -p "test_cli.py" -v
