"""Async wrapper over the git CLI for workflow git operations."""
from __future__ import annotations

import logging
import asyncio
import base64
import os

from app.services.exceptions import GitError


LOG = logging.getLogger(__name__)

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
        LOG.info("git %s (cwd=%s)", " ".join(args), cwd)
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            # Redact the auth header arg so the token never reaches error
            # messages, logs, or the run's surfaced `error`.
            safe = [
                "***" if a.startswith("http.extraheader=") else a
                for a in args
            ]
            raise GitError(
                f"git {' '.join(safe)} -> {proc.returncode}: "
                f"{err.decode('utf-8', 'replace')}"
            )
        return out.decode("utf-8", "replace")

    def _auth(self, token: str | None = None) -> list[str]:
        # Injected per-command so the token never persists in .git/config.
        # Ignored by git for non-http remotes (e.g. local bare repos).
        #
        # GitHub's git-over-HTTPS smart endpoint requires Basic auth (base64
        # "x-access-token:<token>"); a raw "Bearer <token>" header — which
        # does work for the REST API — is rejected with
        # "remote: invalid credentials" / "fatal: Authentication failed".
        # A ``token`` override lets a per-run code host (e.g. a self-hosted
        # GitLab) authenticate with its own credential alongside GitHub;
        # GitLab's git-over-HTTPS accepts the same Basic scheme.
        creds = base64.b64encode(
            f"x-access-token:{token or self.token}".encode()
        ).decode()
        return ["-c", f"http.extraheader=AUTHORIZATION: basic {creds}"]

    async def clone(self, remote_url: str, dest: str) -> None:
        """Clone a remote into dest."""
        await self._git(*self._auth(), "clone", remote_url, dest)
        # Identity for commits made in this workspace.
        await self._git("config", "user.email", "kestrel@local", cwd=dest)
        await self._git("config", "user.name", "kestrel", cwd=dest)

    async def checkout_branch(self, dest: str, branch: str) -> None:
        """Create and switch to a new branch."""
        await self._git("checkout", "-b", branch, cwd=dest)

    async def diff(self, dest: str) -> str:
        """Return the working-tree diff including untracked files."""
        await self._git("add", "-A", cwd=dest)
        return await self._git("diff", "--cached", cwd=dest)

    async def commit_all(self, dest: str, message: str) -> None:
        """Stage everything and commit."""
        await self._git("add", "-A", cwd=dest)
        # Never sign: this is an unattended, headless commit. A machine
        # with commit.gpgsign=true would otherwise block on an
        # interactive pinentry prompt this process can never answer.
        await self._git(
            "-c", "commit.gpgsign=false", "commit", "-m", message, cwd=dest
        )

    async def push(self, dest: str, branch: str) -> None:
        """Push a branch to origin."""
        await self._git(*self._auth(), "push", "origin", branch, cwd=dest)

    # ---- per-run worktree isolation (feature 002, US3) -----------------

    async def ensure_mirror(self, remote_url: str, mirror_dir: str) -> None:
        """
        Ensure a per-repo bare mirror exists and is up to date.

        Clones ``--bare`` on first use, else fetches heads. Serialised per
        mirror so concurrent runs for the same repo don't race the shared
        object DB. No ``--prune`` so an in-flight run's local branch (created
        by ``add_worktree`` before it is pushed) is never deleted.
        """
        async with self._lock_for(mirror_dir):
            if os.path.isdir(mirror_dir):
                await self._git(
                    *self._auth(), "-C", mirror_dir, "fetch", "origin",
                    "+refs/heads/*:refs/heads/*",
                )
            else:
                parent = os.path.dirname(mirror_dir)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                await self._git(
                    *self._auth(), "clone", "--bare", remote_url, mirror_dir
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

    async def provision_worktree(
        self,
        remote_url: str,
        mirror_dir: str,
        dest: str,
        base_branch: str,
        new_branch: str,
    ) -> None:
        """Ensure the mirror, then add the run's isolated worktree."""
        await self.ensure_mirror(remote_url, mirror_dir)
        await self.add_worktree(mirror_dir, dest, base_branch, new_branch)
