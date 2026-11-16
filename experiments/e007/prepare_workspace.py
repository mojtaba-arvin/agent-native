"""Create a minimal agent-visible workspace for one E-007 task."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load_task(task_id: str) -> tuple[dict, str]:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError("invalid_task_id")
    manifest = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
    matches = [task for task in manifest["tasks"] if task["id"] == task_id]
    if len(matches) != 1:
        raise ValueError("unknown_or_ambiguous_task_id")
    task = matches[0]
    source = (ROOT / task["prompt_file"]).read_text(encoding="utf-8")
    marker = f"## {task_id}\n"
    if source.count(marker) != 1:
        raise ValueError("task_prompt_section_missing_or_ambiguous")
    section = source.split(marker, 1)[1]
    next_heading = re.search(r"^## ", section, flags=re.MULTILINE)
    prompt = section[:next_heading.start()] if next_heading else section
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("empty_task_prompt")
    return task, prompt


def prepare_workspace(task_id: str, output: str | Path) -> dict:
    task, prompt = load_task(task_id)
    destination = Path(output).expanduser().absolute()
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("workspace_destination_must_be_missing_or_empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    prompt_bytes = (f"# {task['title']}\n\n{prompt}\n").encode("utf-8")
    manifest = {
        "schema_version": 1,
        "task_id": task_id,
        "difficulty": task["difficulty"],
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "visible_files": ["TASK.md", "workspace-manifest.json"],
        "oracle_material_included": False,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = Path(tempfile.mkdtemp(prefix=".agent-native-workspace-", dir=destination.parent))
    try:
        (temporary / "TASK.md").write_bytes(prompt_bytes)
        (temporary / "workspace-manifest.json").write_bytes(manifest_bytes)
        if destination.exists():
            destination.rmdir()
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_workspace(args.task_id, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
