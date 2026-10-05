"""Tests for the root-contained local TaskSource adapter."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.ports import Task
from app.services.local_task_source import LocalTaskSource
from tests.document_helpers import doc
from tests.local_task_helpers import write_local_task as _write_task


@pytest.mark.asyncio
async def test_get_task_reads_nested_folder(tmp_path) -> None:
    """Ensure root-relative nested references read current task metadata."""
    _write_task(tmp_path, "area/hello")

    task = await LocalTaskSource(str(tmp_path)).get_task("local:area/hello")

    assert task == Task(
        ref="local:area/hello", title="Add a hello endpoint",
        body=doc("Add GET /hello."),
    )


@pytest.mark.asyncio
async def test_posted_comments_are_excluded_without_author(tmp_path) -> None:
    """Ensure the Kestrel filename marker, not author text, prevents loops."""
    _write_task(tmp_path, "hello")
    comments = tmp_path / "hello" / "comments"
    comments.mkdir()
    (comments / "2026-01-01T12.00.00.md").write_text("@kestrel human")
    source = LocalTaskSource(str(tmp_path))

    await source.post_comment("local:hello", doc("@kestrel own reply"))
    feedback = (await source.list_comments("local:hello")).comments

    assert len(feedback) == 1
    assert feedback[0].body == doc("@kestrel human")
    assert feedback[0].created_at == datetime(
        2026, 1, 1, 12, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_human_author_suffix_is_accepted_and_kestrel_is_excluded(
    tmp_path,
) -> None:
    """Accept readable author suffixes without re-reading generated replies."""
    _write_task(tmp_path, "hello")
    comments = tmp_path / "hello" / "comments"
    comments.mkdir()
    (comments / "2026-09-10T12.27.00-malbert.md").write_text("human")
    (comments / "2026-09-10T12.28.00-kestrel.md").write_text("reply")
    (comments / "2026-09-10T12.29.00-kestrel-2.md").write_text("reply")

    page = await LocalTaskSource(str(tmp_path)).list_comments("local:hello")
    feedback = page.comments

    assert [item.body for item in feedback] == [doc("human")]
    assert feedback[0].external_id.endswith("12.27.00-malbert.md")


@pytest.mark.asyncio
async def test_comment_filenames_require_a_valid_markdown_file(
    tmp_path,
) -> None:
    """Ignore filenames with malformed suffixes, extensions, or directories."""
    _write_task(tmp_path, "hello")
    comments = tmp_path / "hello" / "comments"
    comments.mkdir()
    (comments / "2026-09-10T12.27.00-malbert.txt").write_text("bad type")
    (comments / "2026-09-10T12.27.00-.md").write_text("bad suffix")
    (comments / "2026-09-10T12.27.00-note.md").mkdir()

    page = await LocalTaskSource(str(tmp_path)).list_comments("local:hello")

    assert page.comments == []


@pytest.mark.asyncio
async def test_attachments_and_children_stay_inside_task(tmp_path) -> None:
    """Ensure generated task data remains below the parent task folder."""
    _write_task(tmp_path, "hello", base_branch="release")
    source = LocalTaskSource(str(tmp_path))

    await source.attach("local:hello", "note.txt", b"hi", "text/plain")
    child = await source.create_subtask("local:hello", "Child", doc("body"))

    attachment = tmp_path / "hello" / "attachments" / "note.txt"
    assert attachment.read_bytes() == b"hi"
    assert child == "local:hello/children/subtask-1"
    child_task = tmp_path / "hello" / "children" / "subtask-1" / "task.json"
    assert child_task.is_file()
    assert json.loads(child_task.read_text()) == {
        "title": "Child",
        "body": "body",
        "parent": "local:hello",
        "code_repo": "/tmp/sandbox.git",
        "base_branch": "release",
    }


@pytest.mark.asyncio
async def test_rejects_paths_outside_local_task_root(tmp_path) -> None:
    """Ensure task references and attachment names cannot escape their owner."""
    _write_task(tmp_path, "hello")
    source = LocalTaskSource(str(tmp_path))

    with pytest.raises(ValueError):
        await source.get_task("local:../outside")
    with pytest.raises(ValueError):
        await source.attach("local:hello", "../outside", b"", "text/plain")
