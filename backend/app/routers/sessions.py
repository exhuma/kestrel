"""HTTP routes for creating, listing, and streaming sessions."""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.runner import SessionRunner, get_runner
from app.storage.registry import SessionRegistry, get_registry

router = APIRouter(prefix="/api")


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
    runner: SessionRunner = Depends(get_runner),
) -> SessionOut:
    """
    Start a new claude session and return its id.

    :param body: Request body carrying the initial prompt.
    :param runner: Session runner, injected.
    :returns: The id of the newly started session.
    """
    session_id = await runner.start(body.prompt)
    return SessionOut(session_id=session_id)


@router.post("/sessions/{session_id}/resume", response_model=SessionOut)
async def resume_session(
    session_id: str,
    body: PromptIn,
    runner: SessionRunner = Depends(get_runner),
) -> SessionOut:
    """
    Resume an existing session with new input.

    :param session_id: Id of the session to resume.
    :param body: Request body carrying the follow-up prompt.
    :param runner: Session runner, injected.
    :returns: The id of the resumed session.
    """
    try:
        sid = await runner.resume(session_id, body.prompt)
    except KeyError as exc:
        raise HTTPException(404, "unknown session") from exc
    return SessionOut(session_id=sid)


@router.get("/sessions")
async def list_sessions(
    registry: SessionRegistry = Depends(get_registry),
) -> list[dict[str, object]]:
    """
    List all known sessions with status and event counts.

    :param registry: Session registry, injected.
    :returns: One summary dict per session.
    """
    return [
        {
            "session_id": r.session_id,
            "status": r.status,
            "event_count": len(r.events),
        }
        for r in registry.list()
    ]


@router.get("/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    registry: SessionRegistry = Depends(get_registry),
) -> StreamingResponse:
    """
    Stream session events as Server-Sent Events.

    :param session_id: Id of the session to stream events for.
    :param registry: Session registry, injected.
    :returns: A streaming response of SSE event frames.
    """

    async def _gen() -> AsyncIterator[bytes]:
        record = registry.get(session_id)
        if record is not None:
            for ev in list(record.events):
                yield _sse(ev.raw)
        q = registry.subscribe(session_id)
        try:
            while True:
                ev = await q.get()
                yield _sse(ev.raw)
        finally:
            registry.unsubscribe(session_id, q)

    return StreamingResponse(
        _gen(), media_type="text/event-stream"
    )


def _sse(payload: dict[str, object]) -> bytes:
    """Encode a payload as one SSE data frame."""
    return ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")
