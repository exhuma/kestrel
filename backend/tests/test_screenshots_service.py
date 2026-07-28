"""Tests for the screenshot discovery/persistence/upload helper."""
from __future__ import annotations

import os
import shutil

import pytest

from app.models_workflow import WorkflowRun
from app.services.workflows import screenshots


def _run(tmp_path) -> WorkflowRun:
    return WorkflowRun(
        id="run-1", repo="o/r", workspace=str(tmp_path),
        artifact_dir=".kestrel/2026-07-28-001", task_ref="o/r#1",
    )


def _stage(tmp_path, run: WorkflowRun, stage: str) -> str:
    return os.path.join(
        str(tmp_path), run.artifact_dir, "screenshots", stage
    )


def _write(path: str, data: bytes = b"img") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def test_list_scans_both_stages_and_filters_non_images(tmp_path) -> None:
    """Ensure refine+verify images list, refine first, non-images ignored."""
    run = _run(tmp_path)
    _write(os.path.join(_stage(tmp_path, run, "refine"), "a.png"))
    _write(os.path.join(_stage(tmp_path, run, "verify"), "b.jpg"))
    _write(os.path.join(_stage(tmp_path, run, "verify"), "notes.txt"))
    shots = screenshots.list_screenshots(run, str(tmp_path / "durable"))
    pairs = [(s.stage, s.name) for s in shots]
    assert pairs == [("refine", "a.png"), ("verify", "b.jpg")]


def test_list_skips_oversized(tmp_path, monkeypatch) -> None:
    """Ensure a file above the byte cap is not listed."""
    run = _run(tmp_path)
    _write(os.path.join(_stage(tmp_path, run, "refine"), "big.png"), b"x" * 50)
    monkeypatch.setattr(screenshots, "_MAX_BYTES", 10)
    assert screenshots.list_screenshots(run, str(tmp_path / "d")) == []


def test_resolve_path_valid(tmp_path) -> None:
    """Ensure a real in-bounds image resolves to its absolute path."""
    run = _run(tmp_path)
    _write(os.path.join(_stage(tmp_path, run, "verify"), "ok.png"))
    path = screenshots.resolve_path(
        run, "verify", "ok.png", str(tmp_path / "d")
    )
    assert path is not None and path.endswith("verify/ok.png")


@pytest.mark.parametrize(
    "stage,name",
    [
        ("verify", "../../secret.png"),  # traversal
        ("verify", "/etc/passwd"),       # absolute / non-basename
        ("verify", "notes.txt"),         # non-image extension
        ("bogus", "ok.png"),             # unknown stage
        ("verify", "missing.png"),       # not on disk
    ],
)
def test_resolve_path_rejects(tmp_path, stage, name) -> None:
    """Ensure every invalid request collapses to None (a 404)."""
    run = _run(tmp_path)
    assert screenshots.resolve_path(
        run, stage, name, str(tmp_path / "d")
    ) is None


def test_persist_copies_and_survives_worktree_removal(tmp_path) -> None:
    """Ensure persisted shots resolve after the worktree is gone."""
    run = _run(tmp_path)
    _write(os.path.join(_stage(tmp_path, run, "verify"), "s.png"), b"pixels")
    durable = str(tmp_path / "durable")
    screenshots.persist_screenshots(run, durable)
    copied = os.path.join(durable, run.id, "verify", "s.png")
    assert os.path.isfile(copied)
    shutil.rmtree(os.path.join(str(tmp_path), ".kestrel"))
    path = screenshots.resolve_path(run, "verify", "s.png", durable)
    assert path == os.path.realpath(copied)


@pytest.mark.asyncio
async def test_upload_is_best_effort(tmp_path) -> None:
    """Ensure a raising attach never propagates out of upload."""
    run = _run(tmp_path)
    _write(os.path.join(_stage(tmp_path, run, "verify"), "s.png"))

    class _BoomSource:
        calls = 0

        async def attach(self, *_args) -> None:
            _BoomSource.calls += 1
            raise RuntimeError("nope")

    await screenshots.upload_screenshots(
        _BoomSource(), run, str(tmp_path / "d"), "verify"
    )
    assert _BoomSource.calls == 1


@pytest.mark.asyncio
async def test_upload_sends_bytes_and_mimetype(tmp_path) -> None:
    """Ensure upload passes the file bytes and mimetype to attach."""
    run = _run(tmp_path)
    _write(os.path.join(_stage(tmp_path, run, "refine"), "m.png"), b"PIX")
    captured: dict[str, object] = {}

    class _Source:
        async def attach(self, ref, name, data, mimetype) -> None:
            captured.update(
                ref=ref, name=name, data=data, mimetype=mimetype
            )

    await screenshots.upload_screenshots(
        _Source(), run, str(tmp_path / "d"), "refine"
    )
    assert captured == {
        "ref": "o/r#1", "name": "m.png",
        "data": b"PIX", "mimetype": "image/png",
    }
