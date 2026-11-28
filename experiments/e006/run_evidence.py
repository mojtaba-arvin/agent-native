from __future__ import annotations

import argparse
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    started = datetime.now(timezone.utc)
    suite = unittest.defaultTestLoader.discover(str(root), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    finished = datetime.now(timezone.utc)
    report = {
        "schema_version": 1,
        "experiment": "E-006",
        "commit": os.environ.get("E006_TESTED_SHA", os.environ.get("GITHUB_SHA", "local-unpinned")),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "status": "passed" if result.wasSuccessful() else "failed",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "failure_details": [
            {"test": test.id(), "traceback": detail}
            for test, detail in [*result.failures, *result.errors]
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
