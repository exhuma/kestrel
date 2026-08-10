"""Filesystem artifact and debug-log helpers for a workflow run."""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from app.backends.base import Capability
from app.models_workflow import WorkflowRun
from app.services.workflows import screenshots

if TYPE_CHECKING:
    from app.services.workflows import WorkflowService

_logger = logging.getLogger(__name__)

#: Top-level folder (worktree-relative) under which a run's step-handover
#: artifacts live, spec-kit's ``.specify`` in spirit. Each run gets a unique
#: dated subfolder (``.kestrel/<YYYY-MM-DD>-<serial>/``) so artifacts from
#: different change-tickets, once committed, never collide in the repo.
ARTIFACT_ROOT = ".kestrel"

#: Cap on a single ``debug_log`` entry — defense-in-depth against any
#: future entry (not just the diff) ballooning ``dialogue.log``.
_MAX_DEBUG_LOG_ENTRY = 4000


def mirror_dir(workspace_root: str, repo: str) -> str:
    """Path of the per-repo shared bare mirror."""
    return os.path.join(
        workspace_root, "repos", repo.replace("/", "__") + ".git"
    )


def ensure_artifact_dir(
    run: WorkflowRun, save: Callable[[WorkflowRun], None]
) -> None:
    """Pick (once) this run's ``.kestrel/<date>-<serial>/`` folder.

    Idempotent: a run that already has an ``artifact_dir`` (a resumed
    run, restored from the DB) keeps it, so it writes to the same folder
    across a restart. The serial is the next free counter for today's
    date, found by scanning the worktree — so a repo that already carries
    earlier runs' committed artifacts never collides.
    """
    if run.artifact_dir:
        return
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root = os.path.join(run.workspace, ARTIFACT_ROOT)
    existing = set(os.listdir(root)) if os.path.isdir(root) else set()
    serial = 1
    while f"{date}-{serial:03d}" in existing:
        serial += 1
    rel = os.path.join(ARTIFACT_ROOT, f"{date}-{serial:03d}")
    os.makedirs(os.path.join(run.workspace, rel), exist_ok=True)
    run.artifact_dir = rel
    save(run)


def write_artifact(
    run: WorkflowRun,
    filename: str,
    content: str,
    save: Callable[[WorkflowRun], None],
) -> None:
    """Write a handover artifact into this run's artifact folder."""
    ensure_artifact_dir(run, save)
    path = os.path.join(run.workspace, run.artifact_dir, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def artifact_slot(
    step: str,
    run: WorkflowRun,
    filename: str,
    content: str,
    backend_for: Callable[[str], object],
) -> str:
    """Value to interpolate for a prior artifact in a step's prompt.

    A file-capable backend (claude, opencode) is pointed at the file so
    the large PRD/design text stays out of the prompt; a text-only
    backend (a plain LLM, which cannot read the worktree) still gets the
    content inlined, exactly as before.
    """
    backend = backend_for(step)
    if Capability.FILE_EDITS in backend.caps:
        relpath = os.path.join(run.artifact_dir, filename)
        return (
            f"(Provided as a file in the working tree at `{relpath}` — "
            "read it in full before proceeding.)"
        )
    return content


def debug_log(
    run: WorkflowRun, heading: str, content: str, *, enabled: bool
) -> None:
    """Append one entry to the run's coder<->verifier dialogue transcript.

    A no-op unless ``enabled`` (the ``workflow_debug`` setting). Written
    to a *sibling* of the worktree (``<workspace>-debug/``), not inside
    it, so it is never staged/committed — this is a local debugging aid,
    not a deliverable artifact. One flat, human-readable log rather than
    the raw session stream, which buries the coder<->verifier exchange
    in tool-call noise. Any single entry is capped at
    ``_MAX_DEBUG_LOG_ENTRY`` — defense in depth against a future verbose
    entry (e.g. an explore-turn narrative) ballooning the file, on top of
    specific entries (like the diff) already being bounded at the source.
    """
    if not enabled:
        return
    debug_dir = f"{run.workspace}-debug"
    os.makedirs(debug_dir, exist_ok=True)
    path = os.path.join(debug_dir, "dialogue.log")
    rule = "=" * 78
    body = content.rstrip()
    if len(body) > _MAX_DEBUG_LOG_ENTRY:
        omitted = len(body) - _MAX_DEBUG_LOG_ENTRY
        body = (
            f"{body[:_MAX_DEBUG_LOG_ENTRY]}\n"
            f"...[truncated {omitted} of {len(body)} chars]"
        )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"\n{rule}\n{heading}\n{rule}\n{body}\n")


async def teardown_workspace(
    service: "WorkflowService", run: WorkflowRun, *, force: bool = False
) -> None:
    """Remove a run's worktree and debug sibling; best-effort and isolated.

    Closes the workspace leak (only abandon cleaned up before) so a
    finished/failed run does not linger. Never disturbs another run's
    worktree (feature 002, FR-017). Skipped when ``workflow_debug`` is on
    — the worktree and its dialogue transcript (see :func:`debug_log`)
    stay inspectable — unless ``force``, which an explicit abandon still
    uses to actually drop the workspace on request.
    """
    if not run.workspace:
        return
    if service.settings.workflow_debug and not force:
        _logger.info(
            "workflow_debug: keeping workspace for run %s (%s)",
            run.id, run.workspace,
        )
        return
    # Preserve this run's screenshots to the durable dir before the
    # worktree they live in is removed, so the gallery keeps working
    # once the run is done/failed. Best-effort, never blocks teardown.
    with contextlib.suppress(Exception):
        screenshots.persist_screenshots(run, service.settings.screenshots_root)
    with contextlib.suppress(Exception):
        await service.git.remove_worktree(
            mirror_dir(service.settings.workspace_root, run.repo),
            run.workspace,
        )
    shutil.rmtree(run.workspace, ignore_errors=True)
    shutil.rmtree(f"{run.workspace}-debug", ignore_errors=True)
