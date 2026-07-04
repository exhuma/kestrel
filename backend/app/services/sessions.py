"""Session orchestration service.

The single collaborator the routers depend on. Owns business rules
(existence checks, status transitions), event-stream shaping, and
delegation to the subprocess runner. Holds no HTTP concepts.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import AsyncIterator

from fastapi import Depends

from app import sse
from app.backends.base import Backend
from app.backends.registry import get_backend_registry
from app.models import CanonicalEvent
from app.schemas import SessionSummary
from app.services.exceptions import SessionNotFoundError
from app.storage.registry import SessionRegistry, get_registry
from app.storage.workflow_registry import (
    WorkflowRegistry,
    get_workflow_registry,
)


class SessionService:
    """Coordinates a dispatch backend and the registry behind one API."""

    def __init__(
        self,
        backend: Backend,
        registry: SessionRegistry,
        workflows: WorkflowRegistry | None = None,
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.workflows = workflows

    async def start(self, prompt: str) -> str:
        """
        Start a new session.

        :param prompt: The initial prompt text.
        :returns: The resolved session id.
        """
        return await self.backend.start(prompt)

    async def resume(self, session_id: str, prompt: str) -> str:
        """
        Resume an existing session with new input.

        :param session_id: Id of the session to resume.
        :param prompt: The follow-up prompt text.
        :returns: The resolved session id.
        :raises SessionNotFoundError: If the session is unknown.
        """
        if self.registry.get(session_id) is None:
            raise SessionNotFoundError(session_id)
        self.registry.set_status(session_id, "running")
        return await self.backend.resume(session_id, prompt)

    def delete(self, session_id: str) -> None:
        """
        Abandon a session: kill its subprocess and drop all its state.

        Terminates the live claude subprocess (if any), then removes the
        registry record and its persisted rows. Purely local — touches
        nothing external.

        :param session_id: Id of the session to abandon.
        :raises SessionNotFoundError: If the session is unknown.
        """
        if self.registry.get(session_id) is None:
            raise SessionNotFoundError(session_id)
        self.backend.terminate(session_id)
        self.registry.remove(session_id)

    def list_summaries(self) -> list[SessionSummary]:
        """
        Summarise all known sessions, each linked to its workflow.

        A session is attributed to a workflow run when it ran in that
        run's workspace — this catches every session the run spawned
        (the coordinator, each specialist, plan, implement), not just
        the latest one a step happens to still point at.

        :returns: One summary per session, in insertion order.
        """
        wf_by_workspace: dict[str, str] = {}
        if self.workflows is not None:
            for run in self.workflows.list():
                if run.workspace:
                    wf_by_workspace[run.workspace] = (
                        f"{run.repo}#{run.issue_number}"
                    )
        return [
            SessionSummary(
                session_id=r.session_id,
                status=r.status,
                event_count=len(r.events),
                created_at=r.created_at,
                workflow=wf_by_workspace.get(r.cwd),
            )
            for r in self.registry.list()
        ]

    async def stream(
        self, session_id: str
    ) -> AsyncIterator[dict[str, object] | None]:
        """
        Yield event payloads for a session: replay then live.

        Replays already-recorded events, then streams new ones as they
        arrive, interleaving ``None`` keepalive ticks so a session that
        goes quiet (e.g. a slow model generating) doesn't leave the SSE
        connection idle and drop. Unknown sessions yield nothing and
        register no subscriber, so no queue leaks. The subscriber is
        always removed on exit.

        :param session_id: Id of the session to stream.
        :returns: Canonical event dicts, interleaved with ``None``
            keepalive ticks.
        """
        record = self.registry.get(session_id)
        if record is None:
            return
        for ev in list(record.events):
            yield _payload(ev)
        q = self.registry.subscribe(session_id)
        try:
            async for ev in sse.with_heartbeat(q):
                yield None if ev is None else _payload(ev)
        finally:
            self.registry.unsubscribe(session_id, q)


def _payload(event: CanonicalEvent) -> dict[str, object]:
    """
    Shape a canonical event into the wire ``SessionEvent`` contract.

    :param event: The canonical event to serialise.
    :returns: A JSON-ready canonical event dict.
    """
    data = asdict(event)
    data["kind"] = event.kind.value
    return data


def get_session_service(
    registry: SessionRegistry = Depends(get_registry),
) -> SessionService:
    """
    Provide a SessionService as a FastAPI dependency.

    :param registry: Session registry singleton, injected.
    :returns: A SessionService bound to the default session backend.
    """
    backend = get_backend_registry().default_session_backend()
    return SessionService(backend, registry, get_workflow_registry())
