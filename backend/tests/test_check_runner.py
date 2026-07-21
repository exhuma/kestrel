"""Tests for the v1 verify evidence gatherer (CheckRunner, feature 003)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.checks import CheckRunner


@pytest.mark.asyncio
async def test_no_checks_returns_empty_evidence(tmp_path: Path) -> None:
    """Ensure an unconfigured runner returns empty Evidence (judgment-only)."""
    evidence = await CheckRunner([]).run(str(tmp_path))
    assert evidence.observations == []
    assert evidence.all_passed() is True


@pytest.mark.asyncio
async def test_passing_and_failing_checks(tmp_path: Path) -> None:
    """Ensure exit code maps to passed and both outcomes are captured."""
    evidence = await CheckRunner(
        ["true", "sh -c 'echo boom >&2; exit 1'"]
    ).run(str(tmp_path))
    assert [o.passed for o in evidence.observations] == [True, False]
    assert evidence.all_passed() is False
    fail = evidence.failures()[0]
    assert fail.kind == "check"
    assert "boom" in fail.detail


@pytest.mark.asyncio
async def test_check_runs_in_workspace_cwd(tmp_path: Path) -> None:
    """Ensure checks run with the worktree as cwd."""
    (tmp_path / "marker.txt").write_text("x")
    evidence = await CheckRunner(["test -f marker.txt"]).run(str(tmp_path))
    assert evidence.observations[0].passed is True


@pytest.mark.asyncio
async def test_detail_is_bounded(tmp_path: Path) -> None:
    """Ensure captured output is truncated so evidence stays bounded."""
    evidence = await CheckRunner(
        ["sh -c 'head -c 100000 /dev/zero | tr \"\\0\" a'"]
    ).run(str(tmp_path))
    assert len(evidence.observations[0].detail) <= 2000


@pytest.mark.asyncio
async def test_unknown_command_fails_gracefully(tmp_path: Path) -> None:
    """Ensure a command that fails to run yields a failed observation."""
    evidence = await CheckRunner(
        ["this-binary-does-not-exist-xyz --nope"]
    ).run(str(tmp_path))
    assert evidence.observations[0].passed is False
