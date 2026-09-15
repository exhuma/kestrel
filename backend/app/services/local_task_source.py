"""File-backed ``TaskSource`` adapter for root-contained local task folders."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from app.documents import Document, as_document, render_markdown
from app.ports import Feedback, LifecycleEvent, Task
from app.services.feedback.marker import append_comment_sentinel
from app.services.feedback.timeparse import parse_iso

_PREFIX = "local:"
_STAMP_FORMAT = "%Y-%m-%dT%H.%M.%S"
_COMMENT_STAMP = r"\d{4}-\d{2}-\d{2}T\d{2}\.\d{2}\.\d{2}"
_HUMAN_COMMENT_NAME = re.compile(
    rf"^(?P<stamp>{_COMMENT_STAMP})(?:-[A-Za-z0-9][A-Za-z0-9_-]*)?\.md$"
)
_KESTREL_COMMENT_NAME = re.compile(rf"^{_COMMENT_STAMP}-kestrel(?:-\d+)?\.md$")


def local_task_ref(path: Path, root: Path) -> str:
    """Return the root-relative local task reference for a task directory."""
    return f"{_PREFIX}{path.resolve().relative_to(root).as_posix()}"


class LocalTaskSource:
    """``TaskSource`` adapter backed by recursive local task folders."""

    def __init__(
        self,
        tasks_dir: str,
        comment_sentinel_enabled: bool = True,
        comment_sentinel: str = "[kestrel:posted]",
    ) -> None:
        self._root = Path(tasks_dir).resolve()
        self._comment_sentinel_enabled = comment_sentinel_enabled
        self._comment_sentinel = comment_sentinel

    def _task_dir(self, ref: str) -> Path:
        """Return a validated, root-contained directory for ``ref``."""
        relative = PurePosixPath(ref.removeprefix(_PREFIX))
        if (
            not ref.startswith(_PREFIX)
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            raise ValueError(f"invalid local task reference: {ref}")
        path = (self._root / relative).resolve()
        if not path.is_relative_to(self._root):
            raise ValueError(f"local task reference escapes root: {ref}")
        return path

    def _task_path(self, ref: str) -> Path:
        """Return the metadata path for a validated local task reference."""
        return self._task_dir(ref) / "task.json"

    def _load(self, ref: str) -> dict:
        """Read current task metadata from the task's folder."""
        return json.loads(self._task_path(ref).read_text(encoding="utf-8"))

    def _contained_path(self, ref: str, directory: str, name: str) -> Path:
        """Return a validated child file path under a task-owned directory."""
        if not name or PurePosixPath(name).name != name:
            raise ValueError(f"invalid local task filename: {name}")
        target_dir = self._task_dir(ref) / directory
        target = (target_dir / name).resolve()
        if not target.is_relative_to(target_dir.resolve()):
            raise ValueError(f"local task filename escapes task: {name}")
        target_dir.mkdir(parents=True, exist_ok=True)
        return target

    async def get_task(self, ref: str) -> Task:
        """Return the current title and body for a local task."""
        data = self._load(ref)
        return Task(ref=ref, title=data["title"], body=data["body"])

    async def check_health(self) -> bool:
        """Report local tasks healthy without an external probe."""
        return True

    async def post_comment(self, ref: str, body: Document | str) -> str:
        """Write a timestamped reply excluded from local task feedback."""
        directory = self._task_dir(ref) / "comments"
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime(_STAMP_FORMAT)
        path = self._unique_comment_path(directory, f"{stamp}-kestrel")
        path.write_text(
            append_comment_sentinel(
                render_markdown(as_document(body)),
                self._comment_sentinel_enabled,
                self._comment_sentinel,
            ),
            encoding="utf-8",
        )
        return str(path)

    def _unique_comment_path(self, directory: Path, stem: str) -> Path:
        """Return an unused Markdown comment path, adding a numeric suffix."""
        path = directory / f"{stem}.md"
        suffix = 2
        while path.exists():
            path = directory / f"{stem}-{suffix}.md"
            suffix += 1
        return path

    async def attach(
        self, ref: str, name: str, data: bytes, _mimetype: str
    ) -> None:
        """Write an attachment under the task's ``attachments`` directory."""
        self._contained_path(ref, "attachments", name).write_bytes(data)

    async def publish_refined(self, ref: str, content: str) -> None:
        """Replace the task body with approved refined content."""
        data = self._load(ref)
        data["body"] = content
        self._task_path(ref).write_text(json.dumps(data), encoding="utf-8")

    async def create_subtask(
        self, parent_ref: str, title: str, body: str
    ) -> str:
        """Create a child task below its root-contained parent folder."""
        parent = self._task_dir(parent_ref)
        children = parent / "children"
        number = 1
        while (children / f"subtask-{number}" / "task.json").exists():
            number += 1
        child = children / f"subtask-{number}"
        child.mkdir(parents=True)
        parent_data = self._load(parent_ref)
        data = {
            "title": title,
            "body": body,
            "parent": parent_ref,
            "code_repo": parent_data.get("code_repo"),
            "base_branch": parent_data.get("base_branch"),
        }
        (child / "task.json").write_text(json.dumps(data), encoding="utf-8")
        return local_task_ref(child, self._root)

    async def complete_subtask(self, _parent_ref: str, _task_ref: str) -> None:
        """No-op because local child creation copies repository context."""

    def display_label(self, ref: str) -> str:
        """Return the root-relative local task path without its prefix."""
        return str(self._task_dir(ref).relative_to(self._root))

    def deep_link_ref(self, _ref: str) -> str:
        """Return no browser link because tasks are local filesystem data."""
        return ""

    async def transition(self, _ref: str, _event: LifecycleEvent) -> bool:
        """Report no native local-task lifecycle transition support."""
        return False

    def supports_time_spent(self) -> bool:
        """Report that local tasks do not have a native time field."""
        return False

    def visibility(self) -> Literal["public", "private"]:
        """Report local tasks as private and therefore rerunnable."""
        return "private"

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """Read human Markdown comments and exclude Kestrel reply files."""
        directory = self._task_dir(ref) / "comments"
        if not directory.is_dir():
            return []
        cutoff = parse_iso(since) if since else None
        return [
            feedback
            for path in sorted(directory.glob("*.md"))
            if (feedback := self._read_human_comment(ref, path, cutoff))
            is not None
        ]

    def _read_human_comment(
        self, ref: str, path: Path, cutoff: datetime | None
    ) -> Feedback | None:
        """Parse one human comment when its name has the required UTC format."""
        if not path.is_file() or _KESTREL_COMMENT_NAME.match(path.name):
            return None
        match = _HUMAN_COMMENT_NAME.match(path.name)
        if match is None:
            return None
        try:
            created = datetime.strptime(match["stamp"], _STAMP_FORMAT).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
        if cutoff is not None and created < cutoff:
            return None
        return Feedback(
            external_id=f"{ref}:{path.name}",
            origin="ticket",
            author="",
            body=path.read_text(encoding="utf-8"),
            created_at=created,
        )

    async def acknowledge(
        self, _feedback: Feedback, _token: str = "eyes"
    ) -> bool:
        """Report no reaction capability for local task comments."""
        return False

    async def cleanup_artifact(self, kind: str, external_id: str) -> str:
        """Remove a Kestrel-created local file or child task when present."""
        if kind == "source_body":
            ref, _, body = external_id.partition("\0")
            data = self._load(ref)
            data["body"] = body
            self._task_path(ref).write_text(json.dumps(data), encoding="utf-8")
            return "cleaned"
        path = Path(external_id)
        if kind == "comment" and path.is_file():
            path.unlink()
            return "cleaned"
        if kind == "subtask":
            path = self._task_dir(external_id)
            if path.exists():
                shutil.rmtree(path)
                return "cleaned"
        return "absent"
