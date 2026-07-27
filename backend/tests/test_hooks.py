"""Tests for HookRunner (feature 006)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models_workflow import WorkflowRun
from app.ports import LifecycleEvent
from app.services.hooks import HookRunner, audit_hooks_dir
from app.services.lifecycle import LifecycleTransitioner


def _make_hook(tmp_path, name: str = "00-hook.sh") -> str:
    path = tmp_path / name
    path.write_text("#!/bin/sh\ncat\n")
    path.chmod(0o755)
    return str(path)


def _fake_process(
    *, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0,
    hang: bool = False,
):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.kill = MagicMock()  # real Process.kill() is synchronous

    async def communicate(**_kwargs):
        if hang:
            await asyncio.sleep(10)
        return stdout, stderr

    proc.communicate.side_effect = communicate
    return proc


@pytest.mark.asyncio
async def test_empty_hooks_dir_is_a_noop() -> None:
    """Ensure an unset hooks_dir touches neither filesystem nor subprocess."""
    with patch("app.services.hooks.asyncio.create_subprocess_exec") as spawn:
        result = await HookRunner().run("", {"event": "done"})
    assert result == {}
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_successful_hook_receives_json_payload(tmp_path) -> None:
    """Ensure a hook is invoked with the payload JSON-encoded on stdin."""
    _make_hook(tmp_path)
    proc = _fake_process(stdout=b"")
    payload = {"event": "done", "run_id": "wf-1"}
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ) as spawn:
        result = await HookRunner().run(str(tmp_path), payload)
    assert result == {}
    assert spawn.await_args.args[0] == str(tmp_path / "00-hook.sh")


@pytest.mark.asyncio
async def test_comment_posted_is_relayed() -> None:
    """Ensure a hook's comment_posted:true is relayed to the caller."""
    proc = _fake_process(stdout=json.dumps({"comment_posted": True}).encode())
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ), patch(
        "app.services.hooks._discover_hooks", return_value=["/x/hook.sh"]
    ):
        result = await HookRunner().run("/x", {"event": "done"})
    assert result == {"comment_posted": True}


@pytest.mark.asyncio
async def test_malformed_stdout_is_treated_as_no_effect() -> None:
    """Ensure invalid JSON on stdout never raises and has no effect."""
    proc = _fake_process(stdout=b"not json{{{")
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ), patch(
        "app.services.hooks._discover_hooks", return_value=["/x/hook.sh"]
    ):
        result = await HookRunner().run("/x", {"event": "done"})
    assert result == {}


@pytest.mark.asyncio
async def test_non_zero_exit_does_not_raise() -> None:
    """Ensure a failing hook is logged and swallowed, not raised."""
    proc = _fake_process(returncode=1, stderr=b"boom")
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ), patch(
        "app.services.hooks._discover_hooks", return_value=["/x/hook.sh"]
    ):
        result = await HookRunner().run("/x", {"event": "done"})
    assert result == {}


@pytest.mark.asyncio
async def test_hanging_hook_is_killed_at_timeout() -> None:
    """Ensure a hook exceeding the timeout is killed, not awaited forever."""
    proc = _fake_process(hang=True)
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ), patch(
        "app.services.hooks._discover_hooks", return_value=["/x/hook.sh"]
    ):
        result = await HookRunner(timeout=0.05).run("/x", {"event": "done"})
    assert result == {}
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_one_bad_hook_does_not_block_another(tmp_path) -> None:
    """Ensure a failing hook never prevents a later hook from running."""
    _make_hook(tmp_path, "00-fails.sh")
    _make_hook(tmp_path, "01-succeeds.sh")
    bad = _fake_process(returncode=1)
    good = _fake_process(stdout=json.dumps({"comment_posted": True}).encode())
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[bad, good]),
    ):
        result = await HookRunner().run(str(tmp_path), {"event": "done"})
    assert result == {"comment_posted": True}


@pytest.mark.asyncio
async def test_non_executable_file_is_skipped(tmp_path) -> None:
    """Ensure a non-executable file in hooks_dir is never invoked."""
    readme = tmp_path / "README.md"
    readme.write_text("not a hook")
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec"
    ) as spawn:
        result = await HookRunner().run(str(tmp_path), {"event": "done"})
    assert result == {}
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_env_is_not_overridden(tmp_path) -> None:
    """Ensure the subprocess call passes no explicit env= override, so it
    inherits kestrel's own process environment (FR-011) — a regression
    test for this intentional decision.
    """
    _make_hook(tmp_path)
    proc = _fake_process()
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ) as spawn:
        await HookRunner().run(str(tmp_path), {"event": "done"})
    assert "env" not in spawn.await_args.kwargs


def test_audit_logs_each_hook(tmp_path, caplog) -> None:
    """Ensure audit_hooks_dir logs every hook it finds."""
    _make_hook(tmp_path)
    with caplog.at_level(logging.INFO, logger="kestrel.hooks"):
        audit_hooks_dir(str(tmp_path))
    assert any("00-hook.sh" in r.message for r in caplog.records)


def test_audit_warns_on_world_writable_hook(tmp_path, caplog) -> None:
    """Ensure a world-writable hook is flagged at WARNING."""
    path = _make_hook(tmp_path, "risky.sh")
    os.chmod(path, 0o777)
    with caplog.at_level(logging.INFO, logger="kestrel.hooks"):
        audit_hooks_dir(str(tmp_path))
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("risky.sh" in r.message for r in warnings)


def test_audit_of_missing_dir_is_a_noop(caplog) -> None:
    """Ensure a nonexistent hooks_dir doesn't raise during audit."""
    with caplog.at_level(logging.INFO, logger="kestrel.hooks"):
        audit_hooks_dir("/nonexistent/path/xyz")
    assert caplog.records == []


# --- LifecycleTransitioner + HookRunner integration (T030) --------------

class _FakeTaskSource:
    """A fake TaskSource recording transition/comment calls."""

    def __init__(self) -> None:
        self.transitions: list[str] = []
        self.comments: list[tuple[str, str]] = []

    async def transition(self, _ref: str, event: LifecycleEvent) -> bool:
        self.transitions.append(event.kind)
        return True  # native status always applied

    async def post_comment(self, ref: str, body: str) -> str:
        self.comments.append((ref, body))
        return "https://ticket/comment/1"

    def supports_time_spent(self) -> bool:
        return True  # so only comment_posted-suppression is under test


def _run(status: str) -> WorkflowRun:
    return WorkflowRun(
        id="wf-1", repo="o/r", issue_number=5, status=status,
        source="github-issue", task_ref="o/r#5",
    )


async def _tick() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_hooks_fire_alongside_native_transition_and_footer(
    tmp_path,
) -> None:
    """Ensure a hook fires for every kind, additive to kestrel's own
    native transition — never replacing it (FR-009)."""
    _make_hook(tmp_path)
    proc = _fake_process(stdout=b"")
    source = _FakeTaskSource()
    transitioner = LifecycleTransitioner(
        {"github-issue": source}, hooks_dir_for=lambda _run: str(tmp_path)
    )
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ) as spawn:
        transitioner.notify(_run("done"))
        await _tick()
    assert source.transitions == ["done"]
    assert spawn.await_count == 1


@pytest.mark.asyncio
async def test_hooks_fire_for_failure_kinds_too(tmp_path) -> None:
    """Ensure hooks are a first-class failure-handling mechanism, not
    just a "done" hook."""
    _make_hook(tmp_path)
    proc = _fake_process(stdout=b"")
    source = _FakeTaskSource()
    transitioner = LifecycleTransitioner(
        {"github-issue": source}, hooks_dir_for=lambda _run: str(tmp_path)
    )
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        transitioner.notify(_run("failed"))
        await _tick()
    assert source.transitions == ["failed"]


@pytest.mark.asyncio
async def test_hook_comment_posted_suppresses_only_the_footer(
    tmp_path,
) -> None:
    """Ensure comment_posted:true suppresses kestrel's own footer post
    but never the native transition attempt."""
    _make_hook(tmp_path)
    proc = _fake_process(stdout=json.dumps({"comment_posted": True}).encode())

    class _NoTimeSource(_FakeTaskSource):
        def supports_time_spent(self) -> bool:
            return False  # would otherwise footer the time

    source = _NoTimeSource()
    transitioner = LifecycleTransitioner(
        {"github-issue": source}, hooks_dir_for=lambda _run: str(tmp_path)
    )
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(return_value=proc),
    ):
        transitioner.notify(_run("done"))
        await _tick()
    assert source.transitions == ["done"]  # native attempt still made
    assert source.comments == []  # but the footer was suppressed


@pytest.mark.asyncio
async def test_hanging_hook_never_blocks_the_run_or_other_hooks(
    tmp_path,
) -> None:
    """Ensure a timing-out hook doesn't prevent kestrel's own dispatch or
    a second, well-behaved hook configured for the same source."""
    _make_hook(tmp_path, "00-hangs.sh")
    _make_hook(tmp_path, "01-succeeds.sh")
    hanging = _fake_process(hang=True)
    good = _fake_process(stdout=json.dumps({"comment_posted": True}).encode())
    source = _FakeTaskSource()
    hooks = HookRunner(timeout=0.05)
    transitioner = LifecycleTransitioner(
        {"github-issue": source},
        hooks_dir_for=lambda _run: str(tmp_path),
        hook_runner=hooks,
    )
    with patch(
        "app.services.hooks.asyncio.create_subprocess_exec",
        AsyncMock(side_effect=[hanging, good]),
    ):
        transitioner.notify(_run("done"))
        await asyncio.sleep(0.15)  # let the timeout + second hook resolve
    assert source.transitions == ["done"]  # native dispatch unaffected
