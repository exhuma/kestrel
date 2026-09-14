"""Local bare-repository implementation of the ``CodeHost`` port."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.ports import RequiredCiStatus


class LocalCodeHost:
    """Code host that publishes to absolute local bare repositories only."""

    def _repo_path(self, repo: str) -> Path:
        """Validate and return an absolute local bare repository path."""
        path = Path(repo)
        is_bare = (path / "HEAD").is_file()
        valid = path.is_absolute() and path.is_dir() and is_bare
        if not valid:
            raise ValueError(
                f"local code host requires a bare repository path: {repo}"
            )
        return path.resolve()

    async def get_default_branch(self, repo: str) -> str:
        """Read the symbolic HEAD branch from a local bare repository."""
        path = self._repo_path(repo)
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(path), "symbolic-ref", "--short", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        output, _ = await proc.communicate()
        if proc.returncode:
            raise ValueError(f"local repository has no default branch: {repo}")
        return output.decode().strip()

    def clone_remote(self, repo: str) -> str:
        """Return the validated local bare-repository path used as a remote."""
        return str(self._repo_path(repo))

    def git_credential(self) -> tuple[str, str] | None:
        """Return no credential because local Git paths do not authenticate."""
        return None

    def supports_change_requests(self) -> bool:
        """Report that a local repository has no pull-request mechanism."""
        return False

    async def required_ci_statuses(
        self, _repo: str, _number: int, names: list[str]
    ) -> list[RequiredCiStatus]:
        """Report unsupported local CI checks as pending rather than passing."""
        return [RequiredCiStatus(name, "pending") for name in names]
