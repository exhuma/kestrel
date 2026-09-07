"""Tests for the file-backed fixture TaskSource adapter (feature 008)."""
from __future__ import annotations

import json

import pytest

from app.ports import LifecycleEvent, Task
from app.services.fixture import FixtureTaskSource
from app.services.workflow_text import has_subtask_sentinel
from tests.conftest import _write_fixture_task as _write_task


@pytest.mark.asyncio
async def test_get_task_reads_title_and_body(tmp_path) -> None:
    """Ensure get_task reads the fixture file's title/body fresh."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    task = await source.get_task("fixture:hello-fixture")

    assert task == Task(
        ref="fixture:hello-fixture",
        title="Add a hello endpoint",
        body="Add GET /hello.",
    )


@pytest.mark.asyncio
async def test_get_task_re_reads_on_every_call(tmp_path) -> None:
    """Ensure edits to the fixture file are picked up with no caching."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))
    await source.get_task("fixture:hello-fixture")

    _write_task(tmp_path, "hello-fixture", title="Edited title")
    task = await source.get_task("fixture:hello-fixture")

    assert task.title == "Edited title"


@pytest.mark.asyncio
async def test_get_task_missing_file_raises(tmp_path) -> None:
    """Ensure a deleted/missing fixture file surfaces as a clear error."""
    source = FixtureTaskSource(str(tmp_path))

    with pytest.raises(FileNotFoundError):
        await source.get_task("fixture:does-not-exist")


@pytest.mark.asyncio
async def test_post_comment_writes_local_log_only(tmp_path) -> None:
    """Ensure post_comment appends locally and never touches the network."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    url = await source.post_comment("fixture:hello-fixture", "a comment")

    log_path = tmp_path / "hello-fixture.log"
    assert log_path.exists()
    assert "a comment" in log_path.read_text()
    assert url == str(log_path)


@pytest.mark.asyncio
async def test_attach_writes_local_file_only(tmp_path) -> None:
    """Ensure attach writes into a local attachments directory."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    await source.attach(
        "fixture:hello-fixture", "note.txt", b"hi", "text/plain"
    )

    attached = tmp_path / "hello-fixture.attachments" / "note.txt"
    assert attached.read_bytes() == b"hi"


@pytest.mark.asyncio
async def test_publish_refined_overwrites_body(tmp_path) -> None:
    """Ensure publish_refined rewrites the fixture file's body in place."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    await source.publish_refined("fixture:hello-fixture", "refined body")
    task = await source.get_task("fixture:hello-fixture")

    assert task.body == "refined body"


@pytest.mark.asyncio
async def test_create_subtask_writes_parent_linked_file(tmp_path) -> None:
    """Ensure create_subtask (feature 012) writes a new fixture task file
    with a parent field, never touching the originating file."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    ref = await source.create_subtask(
        "fixture:hello-fixture",
        "Do the thing",
        "Self-contained body <!-- kestrel:subtask -->",
    )

    task = await source.get_task(ref)
    assert task.title == "Do the thing"
    assert has_subtask_sentinel(task.body)
    data = json.loads((tmp_path / f"{ref.split(':', 1)[1]}.json").read_text())
    assert data["parent"] == "fixture:hello-fixture"
    # The parent file itself is untouched.
    parent = await source.get_task("fixture:hello-fixture")
    assert parent.title == "Add a hello endpoint"


@pytest.mark.asyncio
async def test_create_subtask_avoids_filename_collisions(tmp_path) -> None:
    """Ensure two follow-up tasks from the same parent get distinct refs."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    ref1 = await source.create_subtask("fixture:hello-fixture", "One", "a")
    ref2 = await source.create_subtask("fixture:hello-fixture", "Two", "b")

    assert ref1 != ref2


def test_deep_link_ref_is_always_empty(tmp_path) -> None:
    """Ensure deep_link_ref never offers a link (feature 009): a fixture
    task lives in a local file, not a browser-navigable destination."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    assert source.deep_link_ref("fixture:hello-fixture") == ""
    assert source.deep_link_ref("fixture:missing") == ""


def test_display_label_strips_the_fixture_prefix(tmp_path) -> None:
    """Ensure display_label shows the task's slug, not the raw ref
    (feature 009)."""
    source = FixtureTaskSource(str(tmp_path))

    assert source.display_label("fixture:hello-fixture") == "hello-fixture"


@pytest.mark.asyncio
async def test_transition_always_returns_false(tmp_path) -> None:
    """Ensure transition() no-ops (no native lifecycle mechanism)."""
    source = FixtureTaskSource(str(tmp_path))

    applied = await source.transition(
        "fixture:hello-fixture", LifecycleEvent(kind="start")
    )

    assert applied is False


def test_supports_time_spent_is_false(tmp_path) -> None:
    """Ensure supports_time_spent() is always False (no native time field)."""
    source = FixtureTaskSource(str(tmp_path))

    assert source.supports_time_spent() is False


def test_visibility_is_private(tmp_path) -> None:
    """Ensure the fixture source reports private visibility (feature 008)."""
    source = FixtureTaskSource(str(tmp_path))

    assert source.visibility() == "private"
