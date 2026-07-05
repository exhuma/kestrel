"""The backend-agnostic dispatch contract.

Everything above the adapters (session service, and — in a later phase —
the workflow engine) talks only to :class:`Backend` and the canonical
event stream, never to a concrete tool's flags or output format.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol, runtime_checkable


class BackendTurnError(Exception):
    """Raised when a backend turn ends in an error result.

    The agent reported a failure (an auth error like "Not logged in", an
    execution error, …) instead of a usable deliverable. Raising lets the
    workflow driver fail the run loudly with the message, rather than
    passing the error text off as the step's deliverable.
    """


class Capability(str, Enum):
    """What a backend can do, used to match backends to step requirements.

    A backend serves a step when its capabilities are a superset of the
    step's requirement, so a file-editing agent (claude, opencode) can
    also serve a text-only reasoning step, while a plain LLM (``TEXT``
    only) cannot serve a step that needs ``FILE_EDITS``.
    """

    TEXT = "text"
    FILE_EDITS = "file_edits"
    TOOL_USE = "tool_use"


@dataclass
class TurnRequest:
    """One unit of work handed to a backend."""

    prompt: str
    cwd: str
    permission_mode: str
    model: str | None = None
    #: Native session id to resume, or None to start a fresh session.
    resume_id: str | None = None


@dataclass
class TurnResult:
    """The outcome of a completed turn."""

    session_id: str
    #: The authoritative final text (the deliverable the workflow parses).
    final_text: str


@runtime_checkable
class Backend(Protocol):
    """A dispatch target. Adapters implement this for each tool/LLM."""

    id: str
    caps: frozenset[Capability]

    async def start(self, prompt: str) -> str:
        """Start a new session, returning its id once known."""
        ...

    async def resume(self, session_id: str, prompt: str) -> str:
        """Resume an existing session with new input."""
        ...

    async def run_turn(
        self,
        req: TurnRequest,
        on_session_id: Callable[[str], None] | None = None,
    ) -> TurnResult:
        """Run one turn to completion and return its deliverable."""
        ...

    def terminate(self, session_id: str) -> bool:
        """Stop a running session; return True if one was stopped."""
        ...
