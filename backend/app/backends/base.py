"""The backend-agnostic dispatch contract.

Everything above the adapters (the board's dispatch) talks only to
:class:`Backend`, never to a concrete tool's flags or output format.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Literal, Protocol, runtime_checkable


class BackendTurnError(Exception):
    """Raised when a backend turn ends in an error result.

    The agent reported a failure (an auth error like "Not logged in", an
    execution error, …) instead of a usable deliverable. Raising lets the
    workflow driver fail the run loudly with the message, rather than
    passing the error text off as the step's deliverable.
    """


class TurnStopped(BackendTurnError):
    """Raised when kestrel stopped a turn itself (feature 036): the agent
    looped on a tool or ran past its tool-call budget.

    :param reason: A short, safe account naming the tool and the limit —
        built by kestrel, never the backend's own text.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"turn stopped: {reason}")
        self.reason = reason


class Capability(str, Enum):
    """What a backend can do, used to match backends to step requirements.

    A backend serves a step when its capabilities are a superset of the
    step's requirement, so a file-editing agent (claude, opencode) can
    also serve a text-only reasoning step, while a backend limited to ``TEXT``
    cannot serve a step that needs ``FILE_EDITS``.
    """

    TEXT = "text"
    FILE_EDITS = "file_edits"
    TOOL_USE = "tool_use"


#: ``TurnRequest.permission_mode``: the agent may only read and propose.
PERMISSION_READ_ONLY = "read_only"
#: ``TurnRequest.permission_mode``: the agent may edit files and run
#: commands in its working directory.
PERMISSION_EDIT = "edit"


@dataclass
class TurnRequest:
    """One unit of work handed to a backend."""

    prompt: str
    cwd: str
    #: :data:`PERMISSION_READ_ONLY` or :data:`PERMISSION_EDIT`; each
    #: backend maps these onto its own tool's flags.
    permission_mode: str
    model: str | None = None
    #: Native session id to resume, or None to start a fresh session.
    resume_id: str | None = None
    #: Told the tool's name each time the agent calls one, while the turn
    #: runs (feature 036). Backends that cannot see tool calls live never
    #: call it.
    on_tool: Callable[[str], None] | None = None
    #: Told the backend's session id the moment it is known, before the
    #: turn finishes — so the id survives a turn that later fails or times
    #: out.
    on_session_id: Callable[[str], None] | None = None
    #: The card the turn works for, when there is one; tags the turn's
    #: server-log lines (``kestrel.agent``) next to the session id.
    card_id: str | None = None


@dataclass
class TurnResult:
    """The outcome of a completed turn."""

    session_id: str
    #: The authoritative final text (the deliverable the workflow parses).
    final_text: str


@dataclass(frozen=True)
class ModelInfo:
    """One backend-native model and optional ROI-planning metadata."""

    id: str
    coding_quality: float | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None


@dataclass(frozen=True)
class ModelCatalog:
    """A backend's discovered model catalogue or an explicit unknown result."""

    state: Literal["available", "unknown"]
    models: tuple[ModelInfo, ...] = ()


@runtime_checkable
class Backend(Protocol):
    """A dispatch target. Adapters implement this for each tool/LLM."""

    id: str
    caps: frozenset[Capability]

    async def run_turn(
        self,
        req: TurnRequest,
        on_queue_change: Callable[[bool], None] | None = None,
    ) -> TurnResult:
        """Run one turn to completion and return its deliverable."""
        ...

    async def list_models(self) -> ModelCatalog:
        """Return models, or unknown when discovery is unavailable."""
        ...
