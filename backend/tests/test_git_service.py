"""Tests for GitService against a local bare repo (no network)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.exceptions import GitError
from app.services.git import GitService


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _seed_bare_remote(tmp_path: Path) -> Path:
    """Create a bare remote with one commit on main."""
    seed = tmp_path / "seed"
    seed.mkdir()
    _run("git", "init", "-b", "main", cwd=seed)
    _run("git", "config", "user.email", "t@t.io", cwd=seed)
    _run("git", "config", "user.name", "t", cwd=seed)
    (seed / "README.md").write_text("hi\n")
    _run("git", "add", "-A", cwd=seed)
    _run("git", "commit", "-m", "init", cwd=seed)
    bare = tmp_path / "remote.git"
    _run("git", "clone", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


@pytest.mark.asyncio
async def test_clone_branch_commit_push_roundtrip(tmp_path) -> None:
    """Ensure clone/branch/commit/push land a branch on the remote."""
    bare = _seed_bare_remote(tmp_path)
    dest = str(tmp_path / "work")
    svc = GitService(token="unused-locally")

    await svc.clone(str(bare), dest)
    await svc.checkout_branch(dest, "dispatcher/issue-1")
    (Path(dest) / "new.txt").write_text("change\n")
    diff = await svc.diff(dest)
    assert "new.txt" in diff
    await svc.commit_all(dest, "work: add file")
    await svc.push(dest, "dispatcher/issue-1")

    branches = subprocess.run(
        ["git", "branch", "--list", "dispatcher/issue-1"],
        cwd=bare, check=True, capture_output=True, text=True,
    ).stdout
    assert "dispatcher/issue-1" in branches


@pytest.mark.asyncio
async def test_clone_failure_raises_giterror_without_leaking_token(
    tmp_path,
) -> None:
    """Ensure a git failure raises GitError and never leaks the token."""
    svc = GitService(token="super-secret-token")
    with pytest.raises(GitError) as exc:
        await svc.clone(
            str(tmp_path / "no-such-remote"), str(tmp_path / "dest")
        )
    assert "super-secret-token" not in str(exc.value)
