"""Deterministic JSONL request-trace artifact writer for E-002."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def write_request_traces(path: str | Path, records: Iterable[dict]) -> dict:
    """Write immutable JSONL request observations and return their digest.

    Files are created exclusively so a prior evidence artifact is never
    overwritten accidentally. Credentials and response bodies are not part
    of the trace record schema.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            line = json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ) + "\n"
            encoded = line.encode("utf-8")
            stream.write(line)
            digest.update(encoded)
            count += 1
    return {
        "path": destination.as_posix(),
        "records": count,
        "sha256": digest.hexdigest(),
        "format": "jsonl",
        "schema_version": 1,
    }
