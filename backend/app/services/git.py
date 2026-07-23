"""Async wrapper over the git CLI for workflow git operations."""
from __future__ import annotations

import asyncio
import base64
import logging
import os

from app.services.exceptions import GitError

LOG = logging.getLogger(__name__)


def _redact(args: tuple[str, ...]) -> list[str]:
    """Mask the injected auth header so the token never reaches logs/errors."""
    return [
        "***" if a.startswith("http.extraheader=") else a for a in args
    ]


class GitService:
    """Runs git commands; injects auth per-command, never into config."""

    def __init__(self, token: str) -> None:
        """
        :param token: Token used for the http.extraheader on remote ops.
        """
        self.token = token
        #: Per-repo mirror locks, serialising fetch + worktree add/remove on
        #: the shared object DB (feature 002, US3). Keyed by mirror dir.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, mirror_dir: str) -> asyncio.Lock:
        return self._locks.setdefault(mirror_dir, asyncio.Lock())

    async def _git(self, *args: str, cwd: str | None = None) -> str:
        # Headless: disable any inherited credential helper (e.g. a GitLab
        # OAuth browser flow) and never prompt on a 401 — fail fast instead of
        # hanging on an interactive prompt this process can never answer.
        args = ("-c", "credential.helper=", *args)
        LOG.info("git %s (cwd=%s)", " ".join(_redact(args)), cwd)
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
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

    def _auth(self, cred: tuple[str, str] | None = None) -> list[str]:
        # Injected per-command so the token never persists in .git/config.
        # Ignored by git for non-http remotes (e.g. local bare repos).
        #
        # git-over-HTTPS requires Basic auth (a raw "Bearer <token>" header —
        # which works for the REST API — is rejected with "invalid
        # credentials"). ``cred`` is the run's code-host ``(username, token)``:
        # ``x-access-token`` for GitHub, ``oauth2`` for GitLab. It defaults to
        # this service's own token (GitHub) when a caller passes none.
        username, token = cred if cred else ("x-access-token", self.token)
        creds = base64.b64encode(f"{username}:{token}".encode()).decode()
        return ["-c", f"http.extraheader=AUTHORIZATION: basic {creds}"]

    async def clone(
        self, remote_url: str, dest: str, cred: tuple[str, str] | None = None
    ) -> None:
        """Clone a remote into dest."""
        await self._git(*self._auth(cred), "clone", remote_url, dest)
        # Identity for commits made in this workspace.
        await self._git("config", "user.email", "kestrel@local", cwd=dest)
        await self._git("config", "user.name", "kestrel", cwd=dest)

    async def checkout_branch(self, dest: str, branch: str) -> None:
        """Create and switch to a new branch."""
        await self._git("checkout", "-b", branch, cwd=dest)

    async def diff(self, dest: str, exclude: str | None = None) -> str:
        """Return the working-tree diff including untracked files.

        :param dest: The worktree to diff.
        :param exclude: Optional top-level path (e.g. ``".kestrel"``) whose
            changes are omitted from the returned diff. It is still staged
            (so a later ``commit_all`` commits it) — only the diff view hides
            it, keeping handover artifacts out of the code diff the verifier
            weighs and the code step stores.
        """
        await self._git("add", "-A", cwd=dest)
        args = ["diff", "--cached"]
        if exclude:
            args += ["--", ".", f":(exclude){exclude}"]
        return await self._git(*args, cwd=dest)

    async def commit_all(self, dest: str, message: str) -> None:
        """Stage everything and commit."""
        await self._git("add", "-A", cwd=dest)
        # Never sign: this is an unattended, headless commit. A machine
        # with commit.gpgsign=true would otherwise block on an
        # interactive pinentry prompt this process can never answer.
        await self._git(
            "-c", "commit.gpgsign=false", "commit", "-m", message, cwd=dest
        )

    async def push(
        self, dest: str, branch: str, cred: tuple[str, str] | None = None
    ) -> None:
        """Push a branch to origin."""
        await self._git(*self._auth(cred), "push", "origin", branch, cwd=dest)

    # ---- per-run worktree isolation (feature 002, US3) -----------------

    async def ensure_mirror(
        self,
        remote_url: str,
        mirror_dir: str,
        cred: tuple[str, str] | None = None,
    ) -> None:
        """
        Ensure a per-repo bare mirror exists and is up to date.

        Clones ``--bare`` on first use, else fetches heads. ``cred`` is the
        run's code-host ``(username, token)`` for git-over-HTTPS. Serialised per
        mirror so concurrent runs for the same repo don't race the shared
        object DB. No ``--prune`` so an in-flight run's local branch (created
        by ``add_worktree`` before it is pushed) is never deleted.
        """
        async with self._lock_for(mirror_dir):
            if os.path.isdir(mirror_dir):
                await self._git(
                    *self._auth(cred), "-C", mirror_dir, "fetch", "origin",
                    "+refs/heads/*:refs/heads/*",
                )
            else:
                parent = os.path.dirname(mirror_dir)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                await self._git(
                    *self._auth(cred), "clone", "--bare",
                    remote_url, mirror_dir,
                )

    async def add_worktree(
        self, mirror_dir: str, dest: str, base_branch: str, new_branch: str
    ) -> None:
        """Add an isolated worktree on a new branch off ``base_branch``."""
        async with self._lock_for(mirror_dir):
            await self._git(
                "-C", mirror_dir, "worktree", "add", "-b", new_branch,
                dest, base_branch,
            )
        # Commit identity for this worktree (writes to the shared config).
        await self._git("config", "user.email", "kestrel@local", cwd=dest)
        await self._git("config", "user.name", "kestrel", cwd=dest)

    async def remove_worktree(self, mirror_dir: str, dest: str) -> None:
        """Remove a run's worktree, leaving the mirror and other runs intact."""
        async with self._lock_for(mirror_dir):
            await self._git(
                "-C", mirror_dir, "worktree", "remove", "--force", dest
            )
