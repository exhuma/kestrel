"""Board-domain git workspace provisioning (feature 026, T041).

A trimmed, board-scoped descendant of the deleted ``app/services/git.py``:
a per-repo shared bare mirror plus one worktree per workflow, cut from it
on demand, so a ``read_only``/``write`` card's specialist turn gets a
real, git-backed ``cwd`` instead of ``""`` (see
``dispatch.py::dispatch_ready_work``).

Deliberately out of scope here: push, opening a change request, and any
other "delivery" concern. Kestrel never pushes a coder's work
automatically — that waits for verification (tasks.md T051/T052) to
exist, so nothing unverified reaches a remote. The coder's own prompt
instructs it to commit locally; a later phase decides when (and whether)
to push what it committed.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass

from app.services.exceptions import GitError

_log = logging.getLogger("kestrel.board.workspace")


def _redact(args: tuple[str, ...]) -> list[str]:
    """Mask the injected auth header so the token never reaches logs/errors."""
    return ["***" if a.startswith("http.extraheader=") else a for a in args]


@dataclass(frozen=True)
class WorkspaceRequest:
    """What :meth:`WorkspaceService.ensure_workspace` needs to provision one
    workflow's worktree. Bundled to keep that method's argument count within
    the repo's limit."""

    remote_url: str
    repo: str
    base_branch: str
    workflow_id: str
    cred: tuple[str, str] | None = None


class WorkspaceService:
    """Provisions a per-workflow git worktree from a shared repo mirror."""

    def __init__(self, workspace_root: str) -> None:
        self._root = workspace_root
        #: Per-mirror locks, serialising fetch + worktree add on the shared
        #: object DB (mirrors the deleted services/git.py's own reasoning).
        self._locks: dict[str, asyncio.Lock] = {}

    def mirror_dir(self, repo: str) -> str:
        """Path of the per-repo shared bare mirror."""
        return os.path.join(
            self._root, "repos", repo.replace("/", "__") + ".git"
        )

    def workspace_dir(self, workflow_id: str) -> str:
        """Path of one workflow's worktree."""
        return os.path.join(self._root, "board", workflow_id)

    def _lock_for(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    async def _git(self, *args: str, cwd: str | None = None) -> str:
        # Headless: disable any inherited credential helper and never
        # prompt on a 401 — fail fast instead of hanging.
        args = ("-c", "credential.helper=", *args)
        _log.info("git %s (cwd=%s)", " ".join(_redact(args)), cwd)
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=cwd,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise GitError(
                f"git {' '.join(_redact(args))} -> {proc.returncode}: "
                f"{err.decode('utf-8', 'replace')}"
            )
        return out.decode("utf-8", "replace")

    def _auth(self, cred: tuple[str, str] | None) -> list[str]:
        # Injected per-command so the token never persists in .git/config.
        # None (e.g. a local bare-repo remote) means no auth at all.
        if cred is None:
            return []
        username, token = cred
        creds = base64.b64encode(f"{username}:{token}".encode()).decode()
        return ["-c", f"http.extraheader=AUTHORIZATION: basic {creds}"]

    async def ensure_mirror(
        self, remote_url: str, mirror_dir: str, cred: tuple[str, str] | None
    ) -> None:
        """Ensure a per-repo bare mirror exists and is up to date."""
        async with self._lock_for(mirror_dir):
            if os.path.isdir(mirror_dir):
                await self._git(
                    *self._auth(cred), "-C", mirror_dir, "fetch", "origin",
                    "+refs/heads/*:refs/remotes/origin/*",
                )
                return
            parent = os.path.dirname(mirror_dir)
            if parent:
                os.makedirs(parent, exist_ok=True)
            await self._git(
                *self._auth(cred), "clone", "--bare", remote_url, mirror_dir
            )
            await self._git(
                *self._auth(cred), "-C", mirror_dir, "fetch", "origin",
                "+refs/heads/*:refs/remotes/origin/*",
            )

    async def ensure_workspace(self, request: WorkspaceRequest) -> str:
        """Return this workflow's worktree path, provisioning it if absent.

        Idempotent at the directory level: an already-provisioned
        workspace is returned unchanged (no re-fetch, no reset), so a
        second card's turn in the same workflow never clobbers a
        specialist's in-progress or already-committed local work.

        :raises GitError: If any underlying git command fails.
        """
        dest = self.workspace_dir(request.workflow_id)
        # A worktree's ".git" is a gitdir-pointer *file*, not a directory
        # (unlike a full clone) — check existence, not isdir.
        if os.path.exists(os.path.join(dest, ".git")):
            return dest
        mirror = self.mirror_dir(request.repo)
        await self.ensure_mirror(request.remote_url, mirror, request.cred)
        branch = f"kestrel/board/{request.workflow_id}"
        worktree_dest = os.path.abspath(dest)
        async with self._lock_for(mirror):
            await self._git(
                "-C", mirror, "worktree", "add", "-b", branch,
                worktree_dest, f"origin/{request.base_branch}",
            )
        await self._git(
            "config", "user.email", "kestrel@local", cwd=worktree_dest
        )
        await self._git(
            "config", "user.name", "kestrel", cwd=worktree_dest
        )
        return dest
