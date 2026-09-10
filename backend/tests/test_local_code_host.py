"""Tests for the offline local bare-repository code host."""

from __future__ import annotations

import subprocess

import pytest

from app.services.local_code_host import LocalCodeHost


@pytest.mark.asyncio
async def test_local_code_host_reads_head_and_returns_path(tmp_path) -> None:
    """Ensure an absolute bare repository supplies its default branch."""
    repo = tmp_path / "project.git"
    subprocess.run(["git", "init", "--bare", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "HEAD", "refs/heads/master"],
        check=True,
    )
    host = LocalCodeHost()

    assert await host.get_default_branch(str(repo)) == "master"
    assert host.clone_remote(str(repo)) == str(repo.resolve())
    assert host.git_credential() is None
    assert host.supports_change_requests() is False


@pytest.mark.asyncio
async def test_local_code_host_rejects_non_bare_or_relative_paths(
    tmp_path,
) -> None:
    """Ensure the offline host only accepts local bare repositories."""
    host = LocalCodeHost()

    with pytest.raises(ValueError):
        await host.get_default_branch("relative.git")
    with pytest.raises(ValueError):
        await host.get_default_branch(str(tmp_path))
