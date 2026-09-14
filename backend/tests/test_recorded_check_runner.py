"""Focused tests for deterministic workflow check execution."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.workflows.check_runner import run_recorded_checks

_FAILURE_EXIT_CODE = 2


def _write_contract(workspace: Path, commands: list[dict]) -> None:
    """Write a version-one contract into a test workspace."""
    artifact_dir = workspace / ".kestrel" / "run"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "check-contract.json").write_text(
        json.dumps({"version": 1, "commands": commands}), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_runs_recorded_commands_and_captures_failures(tmp_path) -> None:
    """A non-zero recorded command becomes bounded structured evidence."""
    _write_contract(tmp_path, [{
        "command": "printf failure >&2; exit 2",
        "cwd": ".",
        "timeout_seconds": 1,
        "rationale": "exercise failure reporting",
    }])
    report = await run_recorded_checks(str(tmp_path), ".kestrel/run")
    result = report.results[0]
    assert report.passed() is False
    assert result.exit_code == _FAILURE_EXIT_CODE
    assert result.stderr == "failure"
    assert json.loads(report.to_json())["results"][0]["passed"] is False


@pytest.mark.asyncio
async def test_timeout_and_workspace_escape_are_failed_evidence(
    tmp_path,
) -> None:
    """Timeouts and paths outside the worktree cannot pass a check round."""
    _write_contract(tmp_path, [
        {
            "command": "sleep 2",
            "cwd": ".",
            "timeout_seconds": 1,
            "rationale": "exercise timeout reporting",
        },
        {
            "command": "true",
            "cwd": "..",
            "timeout_seconds": 1,
            "rationale": "must not escape the workspace",
        },
    ])
    report = await run_recorded_checks(str(tmp_path), ".kestrel/run")
    assert report.passed() is False
    assert report.results[0].timed_out is True
    assert "working directory" in report.results[1].stderr
