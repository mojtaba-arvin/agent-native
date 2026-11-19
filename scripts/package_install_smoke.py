#!/usr/bin/env python3
"""Build and test the package in a clean isolated virtual environment."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="agent-native-package-") as temporary:
        environment = Path(temporary) / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-deps", "."],
            cwd=ROOT,
            check=True,
            timeout=180,
        )
        subprocess.run(
            [
                str(python), "-I", "-m", "unittest", "discover",
                "-s", str(ROOT / "tests"), "-p", "test_*.py", "-v",
            ],
            cwd=temporary,
            check=True,
            timeout=45,
        )
        console = environment / ("Scripts/agent-native.exe" if sys.platform == "win32" else "bin/agent-native")
        subprocess.run([str(console), "--version"], cwd=temporary, check=True, timeout=10)
        subprocess.run(
            [
                str(python), "-I", "-c",
                "import agent_native; from agent_native.runtime import ServiceRuntime; "
                "assert agent_native.__version__ == '0.1.0.dev0'; "
                "assert ServiceRuntime.__name__ == 'ServiceRuntime'",
            ],
            cwd=temporary,
            check=True,
            timeout=10,
        )
    print("PACKAGE INSTALL SMOKE PASS: isolated venv, no runtime dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
