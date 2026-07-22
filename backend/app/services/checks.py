"""Verify evidence gatherer (v1 interim; behavioural harness deferred).

Runs the operator-configured ``verify_checks`` commands in a run's isolated
worktree and reports each as a ``check`` observation. The verifier weighs these
(FR-015a); a failing observation forces a rejection (the failing-observation
invariant, enforced in the verify loop).

The **assumed** behavioural harness — run the modified app and exercise its real
boundary (HTTP requests for an API, Playwright for a GUI → ``http``/``ui``
observations) — is designed-for but out of scope for this feature (FR-015b). It
returns the same :class:`~app.ports.Evidence`, so it drops in without a workflow
change.
"""
from __future__ import annotations

import asyncio
import logging

from app.ports import Evidence, Observation

_log = logging.getLogger("kestrel.checks")

#: Cap on captured output per check so evidence stays bounded and no full log
#: (or secret echoed by a command) lands in a comment or the step deliverable.
_MAX_DETAIL = 2000

#: Per-check wall-clock cap; a hung check must not stall the autonomous loop.
_TIMEOUT_SECONDS = 600


class CheckRunner:
    """Runs configured project checks in the worktree, producing Evidence."""

    def __init__(
        self,
        checks: list[str],
        *,
        timeout: float = _TIMEOUT_SECONDS,
    ) -> None:
        self._checks = list(checks)
        self._timeout = timeout

    async def run(self, workspace: str) -> Evidence:
        """
        Run every configured check in ``workspace`` and collect Evidence.

        :param workspace: The run's isolated worktree (cwd for each check).
        :returns: One ``check`` observation per configured command; an empty
            ``Evidence`` when nothing is configured (judgment-only fallback).
        """
        if not self._checks:
            return Evidence()
        observations: list[Observation] = []
        for command in self._checks:
            observations.append(await self._run_one(command, workspace))
        passed = sum(o.passed for o in observations)
        _log.info(
            "verify checks: %d/%d passed in %s",
            passed,
            len(observations),
            workspace,
        )
        return Evidence(observations=observations)

    async def _run_one(self, command: str, workspace: str) -> Observation:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(
                    proc.communicate(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return Observation(
                    name=command,
                    kind="check",
                    passed=False,
                    detail=f"timed out after {self._timeout:g}s",
                )
            detail = out.decode("utf-8", "replace")[-_MAX_DETAIL:]
            return Observation(
                name=command,
                kind="check",
                passed=proc.returncode == 0,
                detail=detail,
            )
        except OSError as exc:
            return Observation(
                name=command,
                kind="check",
                passed=False,
                detail=f"could not run: {exc}",
            )
