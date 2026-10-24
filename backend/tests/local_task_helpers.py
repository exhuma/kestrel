"""Helpers for tests that create root-contained local task folders."""

from __future__ import annotations

import json


def write_local_task(tasks_dir, slug: str, **fields) -> None:
    """Write a local task folder and metadata with optional field overrides."""
    data = {
        "title": "Add a hello endpoint",
        "body": "Add GET /hello.",
        "code_repo": "/tmp/sandbox.git",
        "base_branch": None,
        "generation": None,
    }
    data.update(fields)
    task_dir = tasks_dir / slug
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "task.json").write_text(json.dumps(data))
