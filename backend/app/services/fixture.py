"""File-backed ``TaskSource`` adapter for local, disposable tasks (feature 008).

A fixture task is one JSON file per task under a configured
``fixtures_dir``; the filename stem is its identity (``ref`` is
``"fixture:<stem>"``). No network call is ever made on a fixture task's
behalf — reads, comments, and status all stay on local disk, so retrying a
task through the pipeline never touches a real GitHub issue or Jira ticket.
See ``.specify/specs/008-fixture-task-source/contracts/fixture-task-file.md``
for the on-disk schema this adapter reads and writes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Literal

from app.ports import LifecycleEvent, Task

_PREFIX = "fixture:"


def _slug(ref: str) -> str:
    """The fixture file's stem, stripped of the ``"fixture:"`` prefix."""
    return ref.removeprefix(_PREFIX)


class FixtureTaskSource:
    """``TaskSource`` adapter backed by files under ``fixtures_dir``."""

    def __init__(self, fixtures_dir: str) -> None:
        self._dir = fixtures_dir

    def _task_path(self, ref: str) -> str:
        return os.path.join(self._dir, f"{_slug(ref)}.json")

    def _load(self, ref: str) -> dict:
        with open(self._task_path(ref), encoding="utf-8") as handle:
            return json.load(handle)

    async def get_task(self, ref: str) -> Task:
        data = self._load(ref)
        return Task(ref=ref, title=data["title"], body=data["body"])

    async def post_comment(self, ref: str, body: str) -> str:
        log_path = os.path.join(self._dir, f"{_slug(ref)}.log")
        stamp = datetime.now(timezone.utc).isoformat()
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {body}\n")
        return log_path

    async def attach(
        self, ref: str, name: str, data: bytes, _mimetype: str
    ) -> None:
        attachments_dir = os.path.join(
            self._dir, f"{_slug(ref)}.attachments"
        )
        os.makedirs(attachments_dir, exist_ok=True)
        with open(os.path.join(attachments_dir, name), "wb") as handle:
            handle.write(data)

    async def publish_refined(self, ref: str, content: str) -> None:
        data = self._load(ref)
        data["body"] = content
        with open(self._task_path(ref), "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    async def create_subtask(
        self, parent_ref: str, title: str, body: str
    ) -> str:
        """Write a new fixture task file linked to its parent by ``ref``.

        Never touches any file the (manual, no-argument) fixture poll
        would auto-pick up on its own — creating this file has no
        ingestion side effect, matching every other source's no-retrigger
        contract (feature 012).
        """
        parent_slug = _slug(parent_ref)
        n = 1
        while os.path.exists(
            os.path.join(self._dir, f"{parent_slug}-subtask-{n}.json")
        ):
            n += 1
        slug = f"{parent_slug}-subtask-{n}"
        ref = f"{_PREFIX}{slug}"
        data = {"title": title, "body": body, "parent": parent_ref}
        with open(self._task_path(ref), "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return ref

    def display_label(self, ref: str) -> str:
        """The task's slug, stripped of the internal "fixture:" prefix."""
        return _slug(ref)

    def deep_link_ref(self, _ref: str) -> str:
        """No browsable destination — a fixture task lives in a local file."""
        return ""

    async def transition(self, _ref: str, _event: LifecycleEvent) -> bool:
        """No native lifecycle mechanism; the caller falls back to a footer."""
        return False

    def supports_time_spent(self) -> bool:
        """A fixture task has no native time-tracking field."""
        return False

    def visibility(self) -> Literal["public", "private"]:
        """Fixture tasks are local and admin-only (feature 008)."""
        return "private"
