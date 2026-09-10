"""Helpers for tests that create file-backed fixture tasks."""

from __future__ import annotations

import json


def write_fixture_task(fixtures_dir, slug: str, **fields) -> None:
    """Write one fixture-source task file with optional field overrides."""
    data = {
        "title": "Add a hello endpoint",
        "body": "Add GET /hello.",
        "code_repo": "me/sandbox",
        "base_branch": None,
        "generation": None,
    }
    data.update(fields)
    (fixtures_dir / f"{slug}.json").write_text(json.dumps(data))
