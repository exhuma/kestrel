"""Tests for the file-backed fixture TaskSource adapter (feature 008)."""
from __future__ import annotations

import pytest

from app.ports import LifecycleEvent, Task
from app.services.fixture import FixtureTaskSource
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


def test_deep_link_ref_returns_file_path(tmp_path) -> None:
    """Ensure deep_link_ref returns the fixture file's path, or "" if gone."""
    _write_task(tmp_path, "hello-fixture")
    source = FixtureTaskSource(str(tmp_path))

    assert source.deep_link_ref("fixture:hello-fixture") == str(
        tmp_path / "hello-fixture.json"
    )
    assert source.deep_link_ref("fixture:missing") == ""


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
