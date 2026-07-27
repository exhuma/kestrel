"""Operator hooks: arbitrary executables invoked at lifecycle events
(feature 006).

**Security note**: hook subprocesses inherit kestrel's full process
environment by deliberate design (constitution, Access model — Second
recorded exception), so a hook has access to every credential kestrel
holds. See ``docs/hooks.md``.

Discovery, invocation, and the JSON wire format follow
``.specify/specs/006-task-lifecycle-sync/contracts/hook-wire-format.md``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import stat

_log = logging.getLogger("kestrel.hooks")

#: Hard per-hook timeout (feature 006, clarified). A hook still running
#: after this is killed and that invocation is treated as failed — it
#: never blocks another hook or the run itself.
_HOOK_TIMEOUT_SECONDS = 30.0

#: Bound on how much of a hook's stderr is ever logged (never echoed
#: anywhere ticket-facing — FR-013).
_STDERR_LOG_LIMIT = 500


def _discover_hooks(hooks_dir: str) -> list[str]:
    """Every executable regular file directly inside ``hooks_dir``,
    filename-sorted. Missing/unreadable directories yield no hooks."""
    try:
        names = sorted(os.listdir(hooks_dir))
    except OSError:
        return []
    hooks = []
    for name in names:
        path = os.path.join(hooks_dir, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            hooks.append(path)
    return hooks


def _parse_response(stdout: bytes) -> dict:
    """Parse a hook's stdout as the optional response object.

    Empty, non-JSON, or non-object output is treated as "no effect"
    (``{}``) — a malformed hook must never break the pipeline.
    """
    text = stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


class HookRunner:
    """Invokes every configured hook for a task source's lifecycle event."""

    def __init__(self, timeout: float = _HOOK_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def run(self, hooks_dir: str, payload: dict) -> dict:
        """Invoke every hook in ``hooks_dir`` with ``payload`` on stdin.

        :param hooks_dir: The configured per-source hooks directory
            (empty ⇒ no hooks, returns ``{}`` without touching the
            filesystem).
        :param payload: The lifecycle-event JSON payload (see the wire
            format contract).
        :returns: The merged response — currently just
            ``{"comment_posted": True}`` if any hook claimed it, else
            ``{}``. Never raises.
        """
        if not hooks_dir:
            return {}
        merged: dict = {}
        data = json.dumps(payload).encode("utf-8")
        for path in _discover_hooks(hooks_dir):
            response = await self._invoke_one(path, data)
            if response.get("comment_posted"):
                merged["comment_posted"] = True
        return merged

    async def _invoke_one(self, path: str, data: bytes) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            _log.exception("failed to start hook %s", path)
            return {}
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=data), timeout=self._timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            _log.warning("hook %s timed out after %ss", path, self._timeout)
            return {}
        if proc.returncode != 0:
            excerpt = stderr.decode("utf-8", errors="replace")
            excerpt = excerpt[:_STDERR_LOG_LIMIT]
            _log.warning(
                "hook %s exited %s: %s", path, proc.returncode, excerpt
            )
            return {}
        return _parse_response(stdout)


def audit_hooks_dir(hooks_dir: str) -> None:
    """Log what's found in a configured ``hooks_dir`` at startup
    (feature 006, FR-016) — a lightweight nudge, not an access control.
    """
    if not hooks_dir:
        return
    for path in _discover_hooks(hooks_dir):
        mode = os.stat(path).st_mode
        if mode & (stat.S_IWGRP | stat.S_IWOTH):
            _log.warning("hook %s is group/world-writable", path)
        else:
            _log.info("hook %s", path)
