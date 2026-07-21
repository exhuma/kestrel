"""Tests for GitService against a local bare repo (no network)."""
from __future__ import annotations

import asyncio
import base64
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
    # Disable signing for this throwaway fixture commit: a machine with
    # commit.gpgsign=true globally set would otherwise hang on pinentry.
    _run("git", "-c", "commit.gpgsign=false", "commit", "-m", "init", cwd=seed)
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
    await svc.checkout_branch(dest, "kestrel/issue-1")
    (Path(dest) / "new.txt").write_text("change\n")
    diff = await svc.diff(dest)
    assert "new.txt" in diff
    await svc.commit_all(dest, "work: add file")
    await svc.push(dest, "kestrel/issue-1")

    branches = subprocess.run(
        ["git", "branch", "--list", "kestrel/issue-1"],
        cwd=bare, check=True, capture_output=True, text=True,
    ).stdout
    assert "kestrel/issue-1" in branches


@pytest.mark.asyncio
async def test_commit_all_ignores_repo_gpgsign_setting(tmp_path) -> None:
    """Ensure commit_all never attempts GPG signing, even if the repo
    (or the machine's global config) has commit.gpgsign=true — which
    would otherwise hang the automated commit on an interactive pinentry
    prompt that a headless backend process can never answer."""
    bare = _seed_bare_remote(tmp_path)
    dest = str(tmp_path / "work")
    svc = GitService(token="unused-locally")
    await svc.clone(str(bare), dest)
    # Enable signing locally, scoped to this throwaway clone only — proves
    # our per-command override wins regardless of ambient config.
    _run("git", "config", "commit.gpgsign", "true", cwd=Path(dest))

    (Path(dest) / "new.txt").write_text("change\n")
    await asyncio.wait_for(svc.commit_all(dest, "work: add file"), timeout=5)

    log = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=dest, check=True, capture_output=True, text=True,
    ).stdout
    assert log.strip() == "work: add file"


def test_auth_uses_basic_scheme_github_git_http_accepts() -> None:
    """Ensure _auth sends Basic auth, the scheme GitHub's git-over-HTTPS
    smart endpoint requires (a raw Bearer header is rejected with
    'invalid credentials' even though it works for the REST API)."""
    svc = GitService(token="tok-123")
    args = svc._auth()
    assert args[0] == "-c"
    header = args[1]
    assert header.startswith("http.extraheader=AUTHORIZATION: basic ")
    encoded = header.split("basic ", 1)[1]
    decoded = base64.b64decode(encoded).decode()
    assert decoded == "x-access-token:tok-123"


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


@pytest.mark.asyncio
async def test_worktree_isolation_and_cleanup(tmp_path) -> None:
    """Ensure two worktrees off one mirror are isolated and clean up cleanly."""
    bare = _seed_bare_remote(tmp_path)
    mirror = str(tmp_path / "mirror.git")
    svc = GitService(token="unused-locally")

    dest_a = str(tmp_path / "wtA")
    dest_b = str(tmp_path / "wtB")
    await svc.provision_worktree(
        str(bare), mirror, dest_a, "main", "kestrel/issue-1"
    )
    await svc.provision_worktree(
        str(bare), mirror, dest_b, "main", "kestrel/issue-2"
    )

    # Each worktree has its own branch and files; neither sees the other's.
    (Path(dest_a) / "a.txt").write_text("A\n")
    (Path(dest_b) / "b.txt").write_text("B\n")
    assert not (Path(dest_a) / "b.txt").exists()
    assert not (Path(dest_b) / "a.txt").exists()

    # A run commits + pushes its branch to the remote from its worktree.
    await svc.commit_all(dest_a, "A: work")
    await svc.push(dest_a, "kestrel/issue-1")
    branches = subprocess.run(
        ["git", "branch", "--list"], cwd=bare,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "kestrel/issue-1" in branches

    # Removing A's worktree leaves B's intact.
    await svc.remove_worktree(mirror, dest_a)
    assert not Path(dest_a).exists()
    assert (Path(dest_b) / "b.txt").exists()


@pytest.mark.asyncio
async def test_ensure_mirror_is_idempotent(tmp_path) -> None:
    """Ensure a second ensure_mirror fetches rather than re-cloning."""
    bare = _seed_bare_remote(tmp_path)
    mirror = str(tmp_path / "mirror.git")
    svc = GitService(token="unused-locally")
    await svc.ensure_mirror(str(bare), mirror)
    # Second call must not raise (fetch path over the existing mirror).
    await svc.ensure_mirror(str(bare), mirror)
    assert Path(mirror).is_dir()
