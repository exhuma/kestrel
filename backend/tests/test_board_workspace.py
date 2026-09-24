"""Tests for the board-domain git workspace provisioner (feature 026,
T041), against a local bare repo (no network).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.board.workspace import WorkspaceRequest, WorkspaceService
from app.services.exceptions import GitError


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
    _run("git", "-c", "commit.gpgsign=false", "commit", "-m", "init", cwd=seed)
    bare = tmp_path / "remote.git"
    _run("git", "clone", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


@pytest.mark.asyncio
async def test_ensure_workspace_provisions_a_fresh_worktree(
    tmp_path: Path,
) -> None:
    """A first call clones the mirror and cuts a per-workflow worktree."""
    bare = _seed_bare_remote(tmp_path)
    svc = WorkspaceService(str(tmp_path / "root"))

    dest = await svc.ensure_workspace(
        WorkspaceRequest(str(bare), "o/r", "main", "wf-1")
    )

    assert (Path(dest) / "README.md").exists()
    # The branch lands in the local mirror cut from `bare`, not `bare`
    # itself — pushing it back is deliberately out of scope here (see the
    # module docstring).
    branches = subprocess.run(
        ["git", "branch", "--list", "kestrel/board/wf-1"],
        cwd=svc.mirror_dir("o/r"),
        check=True, capture_output=True, text=True,
    ).stdout
    assert "kestrel/board/wf-1" in branches


@pytest.mark.asyncio
async def test_ensure_workspace_is_idempotent_and_keeps_local_changes(
    tmp_path: Path,
) -> None:
    """A second call for the same workflow reuses the worktree unchanged."""
    bare = _seed_bare_remote(tmp_path)
    svc = WorkspaceService(str(tmp_path / "root"))

    dest = await svc.ensure_workspace(
        WorkspaceRequest(str(bare), "o/r", "main", "wf-1")
    )
    (Path(dest) / "local.txt").write_text("uncommitted work\n")

    dest_again = await svc.ensure_workspace(
        WorkspaceRequest(str(bare), "o/r", "main", "wf-1")
    )

    assert dest_again == dest
    assert (Path(dest) / "local.txt").read_text() == "uncommitted work\n"


@pytest.mark.asyncio
async def test_ensure_workspace_shares_one_mirror_across_workflows(
    tmp_path: Path,
) -> None:
    """Two workflows against the same repo cut worktrees from one mirror."""
    bare = _seed_bare_remote(tmp_path)
    svc = WorkspaceService(str(tmp_path / "root"))

    dest_a = await svc.ensure_workspace(
        WorkspaceRequest(str(bare), "o/r", "main", "wf-a")
    )
    dest_b = await svc.ensure_workspace(
        WorkspaceRequest(str(bare), "o/r", "main", "wf-b")
    )

    assert dest_a != dest_b
    assert Path(svc.mirror_dir("o/r")).is_dir()
    (Path(dest_a) / "a.txt").write_text("A\n")
    (Path(dest_b) / "b.txt").write_text("B\n")
    assert not (Path(dest_a) / "b.txt").exists()
    assert not (Path(dest_b) / "a.txt").exists()


@pytest.mark.asyncio
async def test_ensure_workspace_raises_git_error_for_a_bad_remote(
    tmp_path: Path,
) -> None:
    """A clone failure surfaces as GitError, not an unhandled subprocess
    error."""
    svc = WorkspaceService(str(tmp_path / "root"))

    with pytest.raises(GitError):
        await svc.ensure_workspace(
            WorkspaceRequest(
                str(tmp_path / "does-not-exist.git"), "o/r", "main", "wf-1"
            )
        )
