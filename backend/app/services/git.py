"""Async wrapper over the git CLI for workflow git operations."""
from __future__ import annotations

import asyncio

from app.services.exceptions import GitError


class GitService:
    """Runs git commands; injects auth per-command, never into config."""

    def __init__(self, token: str) -> None:
        """
        :param token: Token used for the http.extraheader on remote ops.
        """
        self.token = token

    async def _git(self, *args: str, cwd: str | None = None) -> str:
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

    def _auth(self) -> list[str]:
        # Injected per-command so the token never persists in .git/config.
        # Ignored by git for non-http remotes (e.g. local bare repos).
        return ["-c", f"http.extraheader=AUTHORIZATION: bearer {self.token}"]

    async def clone(self, remote_url: str, dest: str) -> None:
        """Clone a remote into dest."""
        await self._git(*self._auth(), "clone", remote_url, dest)
        # Identity for commits made in this workspace.
        await self._git("config", "user.email", "dispatcher@local", cwd=dest)
        await self._git("config", "user.name", "agent-dispatcher", cwd=dest)

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
        await self._git("commit", "-m", message, cwd=dest)

    async def push(self, dest: str, branch: str) -> None:
        """Push a branch to origin."""
        await self._git(*self._auth(), "push", "origin", branch, cwd=dest)
