"""What an opencode turn may call, and when kestrel stops it (feature 036).

opencode runs its own agent loop inside one ``POST /message``: model,
tool, model, tool… Left alone, a model stuck on a tool calls it until the
turn times out, and every tool the opencode server offers — the operator's
MCP servers included — is available to it. This bounds both:

* :func:`tools_map` is the per-message ``tools`` map. opencode turns each
  entry into a session permission rule; the *last* matching rule wins,
  and a tool whose last rule is a deny is hidden from the model. So
  ``{"*": False, "read": True}`` is an allowlist. (opencode checks the
  file-writing tools ``write``/``apply_patch`` under ``edit``.)
* :class:`ToolLoopGuard` watches the turn's tool calls on opencode's event
  stream and aborts the session on a loop or a runaway budget.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.backends.opencode_permissions import (
    READ_ONLY_DENY_TOOLS,
    OpenCodeConnection,
)
from app.config import BackendConfig

_logger = logging.getLogger(__name__)

#: A tool part's statuses once its input is complete.
_CALLED = frozenset({"running", "completed", "error"})


@dataclass(frozen=True)
class ToolPolicy:
    """One backend's tool settings (``BackendConfig``)."""

    allowed: tuple[str, ...] | None
    max_calls: int
    max_repeats: int

    @classmethod
    def of(cls, cfg: BackendConfig) -> ToolPolicy:
        allowed = cfg.allowed_tools
        return cls(
            allowed=tuple(allowed) if allowed is not None else None,
            max_calls=cfg.max_tool_calls,
            max_repeats=cfg.max_repeated_tool_calls,
        )


def tools_map(policy: ToolPolicy, read_only: bool) -> dict[str, bool] | None:
    """The message's ``tools`` map, in rule order, or ``None`` for none.

    The read-only denies come last so they win over an allowlist entry.
    """
    tools: dict[str, bool] = {}
    if policy.allowed is not None:
        tools["*"] = False
        tools.update({tool: True for tool in policy.allowed})
    if read_only:
        for tool in sorted(READ_ONLY_DENY_TOOLS):
            tools.pop(tool, None)  # re-insert at the end: last rule wins
            tools[tool] = False
    return tools or None


class ToolLoopGuard:
    """Counts one turn's tool calls; trips on a loop or past the budget.

    :param on_tool: Told each new call's tool name, as it happens.
    """

    def __init__(
        self, policy: ToolPolicy, on_tool: Callable[[str], None] | None
    ) -> None:
        self._policy = policy
        self._on_tool = on_tool
        self._calls: set[str] = set()
        self._same: Counter[tuple[str, str]] = Counter()
        #: Why the turn must stop, once it must; ``None`` until then.
        self.tripped: str | None = None

    def observe(self, part: object) -> bool:
        """Count *part* if it is a new tool call. True only for the call
        that trips the guard."""
        call = _tool_call(part)
        if call is None or call[0] in self._calls:
            return False
        call_id, tool, arguments = call
        self._calls.add(call_id)
        self._tell(tool)
        self._same[(tool, arguments)] += 1
        if self.tripped is not None:
            return False
        self.tripped = self._limit_reached(tool, self._same[(tool, arguments)])
        return self.tripped is not None

    def _limit_reached(self, tool: str, same: int) -> str | None:
        if same >= self._policy.max_repeats:
            return f"it called {tool} {same} times with the same input"
        if len(self._calls) > self._policy.max_calls:
            return f"it made more than {self._policy.max_calls} tool calls"
        return None

    def _tell(self, tool: str) -> None:
        if self._on_tool is None:
            return
        try:
            self._on_tool(tool)
        except Exception:  # a display hook must never break the turn
            _logger.exception("tool-call observer failed")


def _tool_call(part: object) -> tuple[str, str, str] | None:
    """``(call id, tool, canonical input)`` for a called tool part."""
    if not isinstance(part, dict) or part.get("type") != "tool":
        return None
    state = part.get("state")
    call_id, tool = part.get("callID"), part.get("tool")
    if not isinstance(state, dict) or state.get("status") not in _CALLED:
        return None
    if not isinstance(call_id, str) or not isinstance(tool, str):
        return None
    arguments = json.dumps(state.get("input"), sort_keys=True, default=str)
    return call_id, tool, arguments


def guard_watch(
    conn: OpenCodeConnection,
    session_id: str,
    directory: str | None,
    guard: ToolLoopGuard,
) -> Callable[[object], Awaitable[None]]:
    """The event watcher feeding *guard*; aborts the session when it
    trips, which ends the turn's pending ``POST /message``."""

    async def watch(part: object) -> None:
        if not guard.observe(part):
            return
        _logger.warning(
            "opencode session %s: stopping the turn: %s",
            session_id, guard.tripped,
        )
        try:
            await conn.request(
                "POST", f"/session/{session_id}/abort", directory=directory
            )
        except Exception:
            _logger.exception("opencode session %s: abort failed", session_id)

    return watch
