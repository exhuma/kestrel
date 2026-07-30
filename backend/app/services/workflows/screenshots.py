"""Screenshot discovery, durable persistence, and ticket upload for a run.

Screenshots are ordinary files an agent writes into the shared worktree
under this run's artifact folder, in per-stage subfolders::

    <workspace>/<artifact_dir>/screenshots/refine/*.png
    <workspace>/<artifact_dir>/screenshots/verify/*.png

Nothing crosses the backend contract (which is text-only): kestrel simply
scans the shared filesystem. Because ``deliver`` tears the worktree down,
:func:`persist_screenshots` copies them to a durable, ``/data``-backed
location first so the UI keeps serving them after a run finishes.
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models_workflow import WorkflowRun

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.ports import TaskSource

_logger = logging.getLogger(__name__)

#: Subfolder (under a run's artifact dir) holding all screenshots.
SCREENSHOTS_SUBDIR = "screenshots"
#: The stages that can produce screenshots (also the subfolder names).
STAGES: tuple[str, ...] = ("refine", "verify")
#: Cap on a served/uploaded image, defence against a runaway capture.
_MAX_BYTES = 10_000_000

#: Allowed image extensions -> served ``Content-Type``.
_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@dataclass
class Shot:
    """One discovered screenshot on the filesystem."""

    name: str
    stage: str
    path: str
    mimetype: str


def mime_for(name: str) -> str | None:
    """Served mimetype for a filename, or ``None`` if not an allowed image."""
    return _MIME.get(os.path.splitext(name)[1].lower())


def stage_reldir(run: WorkflowRun, stage: str) -> str:
    """Worktree-relative dir an agent writes a stage's screenshots into.

    Handed to a capture prompt so the agent (whose cwd is the worktree)
    writes where :func:`list_screenshots` later looks.
    """
    return os.path.join(run.artifact_dir, SCREENSHOTS_SUBDIR, stage)


def stage_url(run: WorkflowRun, stage: str, name: str) -> str:
    """Relative URL the frontend fetches one screenshot's bytes from."""
    return f"/api/workflows/{run.id}/screenshots/{stage}/{name}"


def _artifact_dir(run: WorkflowRun, stage: str) -> str:
    """Worktree path holding a stage's screenshots (live, pre-teardown)."""
    return os.path.join(run.workspace, stage_reldir(run, stage))


def _durable_dir(run: WorkflowRun, root: str, stage: str) -> str:
    """Durable path for a stage's screenshots (survives worktree teardown)."""
    return os.path.join(root, run.id, stage)


def _stage_dir(run: WorkflowRun, root: str, stage: str) -> str:
    """Preferred read location: the live worktree if present, else durable."""
    live = _artifact_dir(run, stage)
    return live if os.path.isdir(live) else _durable_dir(run, root, stage)


def _scan_dir(directory: str, stage: str) -> list[Shot]:
    """Discover allowed, in-bounds image files directly under ``directory``."""
    shots: list[Shot] = []
    if not os.path.isdir(directory):
        return shots
    for name in sorted(os.listdir(directory)):
        mime = mime_for(name)
        path = os.path.join(directory, name)
        if mime is None or not os.path.isfile(path):
            continue
        if os.path.getsize(path) > _MAX_BYTES:
            continue
        shots.append(Shot(name=name, stage=stage, path=path, mimetype=mime))
    return shots


def list_screenshots(run: WorkflowRun, root: str) -> list[Shot]:
    """Every discoverable screenshot for a run, refine before verify."""
    shots: list[Shot] = []
    for stage in STAGES:
        shots.extend(_scan_dir(_stage_dir(run, root, stage), stage))
    return shots


def _within(candidate: str, base: str) -> bool:
    """Whether ``candidate`` (a realpath) is inside directory ``base``."""
    anchor = os.path.realpath(base)
    return candidate == anchor or candidate.startswith(anchor + os.sep)


def resolve_path(
    run: WorkflowRun, stage: str, name: str, root: str
) -> str | None:
    """Traversal-safe absolute path for one screenshot, or ``None``.

    Rejects an unknown stage, any non-basename name, a non-image
    extension, an escape outside the stage folder, a missing file, or an
    oversized file — every rejection collapses to ``None`` (a 404).
    """
    if stage not in STAGES or name != os.path.basename(name):
        return None
    if mime_for(name) is None:
        return None
    base = _stage_dir(run, root, stage)
    candidate = os.path.realpath(os.path.join(base, name))
    if not _within(candidate, base):
        return None
    if not os.path.isfile(candidate) or os.path.getsize(candidate) > _MAX_BYTES:
        return None
    return candidate


def persist_screenshots(run: WorkflowRun, root: str) -> None:
    """Copy this run's live worktree screenshots to the durable dir.

    Called immediately before ``_teardown_workspace`` removes the
    worktree, so the gallery keeps working once a run is ``done``.
    """
    for stage in STAGES:
        live = _artifact_dir(run, stage)
        if not os.path.isdir(live):
            continue
        dest = _durable_dir(run, root, stage)
        os.makedirs(dest, exist_ok=True)
        _copy_files(live, dest)


def _copy_files(live: str, dest: str) -> None:
    """Copy the regular files directly under ``live`` into ``dest``."""
    for name in os.listdir(live):
        src = os.path.join(live, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, name))


async def upload_screenshots(
    source: "TaskSource", run: WorkflowRun, root: str, stage: str
) -> None:
    """Best-effort: attach a stage's screenshots to the run's ticket.

    Never raises — a failed attachment (unsupported source, size limit,
    transient error) must not fail the run.
    """
    for shot in _scan_dir(_stage_dir(run, root, stage), stage):
        try:
            with open(shot.path, "rb") as handle:
                data = handle.read()
            await source.attach(run.task_ref, shot.name, data, shot.mimetype)
        except Exception:  # noqa: BLE001 — best-effort ticket upload
            _logger.exception(
                "failed to attach screenshot %s for %s",
                shot.name, run.task_ref,
            )
