"""Dependency-free, isolated mutation checks for authentication invariants.

This is a focused mutation gate, not a whole-project mutation score.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "agent_native" / "security.py"

MUTANTS = (
    (
        "SEC-TENANT-001",
        "if grant.tenant_id == context.tenant_id",
        "if True",
    ),
    (
        "SEC-GRANT-EXPIRY-001",
        "if grant.expires_at is None or context.now < grant.expires_at",
        "if True",
    ),
    (
        "SEC-RESOURCE-BOUNDARY-001",
        'return resource == normalized or resource.startswith(normalized.rstrip("/") + "/")',
        'return resource.startswith(normalized.rstrip("/"))',
    ),
    (
        "SEC-TOKEN-SIGNATURE-001",
        "if not hmac.compare_digest(expected, supplied):",
        "if False:",
    ),
    (
        "SEC-TOKEN-EXPIRY-001",
        "or expires_at <= now",
        "or False",
    ),
)


def run() -> dict:
    original = SOURCE.read_text(encoding="utf-8")
    results = []
    with tempfile.TemporaryDirectory(prefix="agent-native-security-mutants-") as temporary:
        temporary_root = Path(temporary)
        for mutant_id, before, after in MUTANTS:
            if original.count(before) != 1:
                raise RuntimeError(f"{mutant_id}: mutation anchor must occur exactly once")
            mutant_root = temporary_root / mutant_id
            package_root = mutant_root / "src" / "agent_native"
            package_root.parent.mkdir(parents=True)
            shutil.copytree(ROOT / "src" / "agent_native", package_root)
            mutant_source = package_root / "security.py"
            mutant_text = mutant_source.read_text(encoding="utf-8")
            if mutant_text.count(before) != 1:
                raise RuntimeError(f"{mutant_id}: copied source mutation anchor is not unique")
            mutant_source.write_text(mutant_text.replace(before, after), encoding="utf-8")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(mutant_root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "tests.test_authentication"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            output = completed.stdout + completed.stderr
            match = re.search(r"Ran (\d+) tests?", output)
            if match is None:
                raise RuntimeError(
                    f"{mutant_id}: targeted tests did not execute correctly: {output[-2000:]}"
                )
            killed = completed.returncode != 0 and "FAILED" in output
            results.append({
                "mutant_id": mutant_id,
                "outcome": "killed" if killed else "survived",
                "test_count": int(match.group(1)),
                "exit_code": completed.returncode,
            })
    survivors = [item["mutant_id"] for item in results if item["outcome"] != "killed"]
    return {
        "scope": "authentication_security_invariants_only",
        "mutants": results,
        "killed": len(results) - len(survivors),
        "total": len(results),
        "passed": not survivors,
        "survivors": survivors,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, sort_keys=True, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
