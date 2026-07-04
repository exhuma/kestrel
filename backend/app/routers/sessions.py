"""HTTP routes for creating, listing, and streaming sessions.

Thin HTTP layer: validate input, call the service, shape responses.
All business logic and storage access live in ``SessionService``.
"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import sse
from app.config import Settings, get_settings
from app.schemas import SessionSummary
from app.services.sessions import SessionService, get_session_service

router = APIRouter(prefix="/api")


@router.get("/backends")
async def list_backends(
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    """
    Report the effective backend configuration.

    A diagnostic: confirms which backends are configured and which one
    ad-hoc sessions dispatch to, so a misread ``.env`` is obvious.

    :param settings: Application settings, injected.
    :returns: The default session backend and the configured backends.
    """
    return {
        "default_session_backend": settings.default_session_backend,
        "backends": [
            {"id": b.id, "type": b.type, "model": b.model}
            for b in settings.backends
        ],
    }


class PromptIn(BaseModel):
    """
    Request body carrying a single prompt string.

    :param prompt: The prompt text to send to the claude session.
    """

    prompt: str


class SessionOut(BaseModel):
    """
    Response body identifying a session.

    :param session_id: Unique id of the session.
    """

    session_id: str


@router.post("/sessions", response_model=SessionOut)
async def create_session(
    body: PromptIn,
    service: SessionService = Depends(get_session_service),
) -> SessionOut:
    """
    Start a new claude session and return its id.

    :param body: Request body carrying the initial prompt.
    :param service: Session service, injected.
    :returns: The id of the newly started session.
    """
    session_id = await service.start(body.prompt)
    return SessionOut(session_id=session_id)


@router.post("/sessions/{session_id}/resume", response_model=SessionOut)
async def resume_session(
    session_id: str,
    body: PromptIn,
    service: SessionService = Depends(get_session_service),
) -> SessionOut:
    """
    Resume an existing session with new input.

    :param session_id: Id of the session to resume.
    :param body: Request body carrying the follow-up prompt.
    :param service: Session service, injected.
    :returns: The id of the resumed session.
    """
    sid = await service.resume(session_id, body.prompt)
    return SessionOut(session_id=sid)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    service: SessionService = Depends(get_session_service),
) -> list[SessionSummary]:
    """
    List all known sessions with status and event counts.

    :param service: Session service, injected.
    :returns: One summary per session.
    """
    return service.list_summaries()


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> dict[str, str]:
    """
    Abandon a session, killing its subprocess and dropping its state.

    :param session_id: Id of the session to abandon.
    :param service: Session service, injected.
    :returns: A simple ok acknowledgement.
    """
    service.delete(session_id)
    return {"status": "ok"}


@router.get("/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> StreamingResponse:
    """
    Stream session events as Server-Sent Events.

    :param session_id: Id of the session to stream events for.
    :param service: Session service, injected.
    :returns: A streaming response of SSE event frames.
    """

    async def _frames() -> AsyncIterator[bytes]:
        async for payload in service.stream(session_id):
            yield sse.encode(payload)

    return StreamingResponse(_frames(), media_type="text/event-stream")
