#!/usr/bin/env python3
"""Validate that the generated SPDX SBOM describes the installed product."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_sbom.py PATH", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("spdxVersion") != "SPDX-2.3":
        raise SystemExit("SBOM must use SPDX-2.3")
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SystemExit("SBOM contains no package inventory")
    names = {
        item.get("name", "").casefold()
        for item in packages
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if "agent-native" not in names:
        raise SystemExit("SBOM does not identify the installed agent-native package")
    if not document.get("creationInfo", {}).get("creators"):
        raise SystemExit("SBOM is missing creator metadata")
    print(f"Validated SPDX-2.3 SBOM: {len(packages)} packages; agent-native present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
