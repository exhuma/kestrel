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
from app.services import liveness
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

    def _workflow_by_workspace(self) -> dict[str, str]:
        wf_by_workspace: dict[str, str] = {}
        if self.workflows is not None:
            for run in self.workflows.list():
                if run.workspace:
                    wf_by_workspace[run.workspace] = (
                        f"{run.repo}#{run.issue_number}"
                    )
        return wf_by_workspace

    def list_summaries(self) -> list[SessionSummary]:
        """
        Summarise all known sessions, each linked to its workflow.

        A session is attributed to a workflow run when it ran in that
        run's workspace — this catches every session the run spawned
        (the coordinator, each specialist, plan, implement), not just
        the latest one a step happens to still point at.

        :returns: One summary per session, in insertion order.
        """
        wf_by_workspace = self._workflow_by_workspace()
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

    async def poll(self, session_id: str) -> SessionSummary:
        """
        Actively probe whether a session is still alive against its
        backend, recording a diagnostic error if it has silently died.

        :param session_id: Id of the session to probe.
        :returns: The session's (possibly now-updated) summary.
        :raises SessionNotFoundError: If the session is unknown.
        """
        record = self.registry.get(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        await liveness.poll_session(self.backend, self.registry, session_id)
        record = self.registry.get(session_id)
        return SessionSummary(
            session_id=record.session_id,
            status=record.status,
            event_count=len(record.events),
            created_at=record.created_at,
            workflow=self._workflow_by_workspace().get(record.cwd),
        )

    async def stream(
        self, session_id: str, resume_after: int = 0
    ) -> AsyncIterator[tuple[int, dict[str, object]] | None]:
        """
        Yield sequenced event payloads for a session: replay then live.

        Replays only events after ``resume_after`` (0 replays everything),
        then streams new ones as they arrive, interleaving ``None``
        keepalive ticks so a session that goes quiet (e.g. a slow model
        generating) doesn't leave the SSE connection idle and drop.
        Sequence numbers are 1-based and stable across a restart (persisted
        events reload in insertion order), so a browser reconnect carrying
        ``Last-Event-ID`` only receives what it missed instead of the full
        history again. Unknown sessions yield nothing and register no
        subscriber, so no queue leaks. The subscriber is always removed on
        exit.

        :param session_id: Id of the session to stream.
        :param resume_after: Skip replaying events at or before this
            sequence number.
        :returns: ``(sequence, payload)`` pairs, interleaved with ``None``
            keepalive ticks.
        """
        record = self.registry.get(session_id)
        if record is None:
            return
        events = list(record.events)
        for index, ev in enumerate(events, start=1):
            if index > resume_after:
                yield index, _payload(ev)
        q = self.registry.subscribe(session_id)
        next_index = len(events) + 1
        try:
            async for ev in sse.with_heartbeat(q):
                if ev is None:
                    yield None
                else:
                    yield next_index, _payload(ev)
                    next_index += 1
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
