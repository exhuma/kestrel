"""HTTP routes for creating, listing, and streaming sessions.

Thin HTTP layer: validate input, call the service, shape responses.
All business logic and storage access live in ``SessionService``.
"""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import sse
from app.backends.registry import BackendRegistry, get_backend_registry
from app.config import Settings, get_settings
from app.schemas import SessionSummary
from app.services.sessions import SessionService, get_session_service

router = APIRouter(prefix="/api")


@router.get("/backends")
async def list_backends(
    settings: Settings = Depends(get_settings),
    registry: BackendRegistry = Depends(get_backend_registry),
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
            {
                "id": b.id,
                "type": b.type,
                "model": b.model,
                "capabilities": sorted(
                    c.value for c in registry.get(b.id).caps
                ),
            }
            for b in settings.backends
        ],
    }


@router.get("/backends/{backend_id}/models")
async def list_backend_models(
    backend_id: str,
    registry: BackendRegistry = Depends(get_backend_registry),
) -> dict[str, object]:
    """Return one configured backend's discovered model catalogue."""
    try:
        catalogue = await registry.get(backend_id).list_models()
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="backend not found"
        ) from exc
    return {
        "backend_id": backend_id,
        "state": catalogue.state,
        "models": [
            {
                "id": model.id,
                "coding_quality": model.coding_quality,
                "input_cost_per_million": model.input_cost_per_million,
                "output_cost_per_million": model.output_cost_per_million,
            }
            for model in catalogue.models
        ],
    }


class PromptIn(BaseModel):
    """
    Request body carrying a single prompt string.

    :param prompt: The prompt text to send to the claude session.
    :param confirmed_injection_risk: Explicit operator confirmation of the
        injection-risk warning shown for a direct prompt (FR-023). A
        direct prompt intentionally addresses an agent, so it is not
        automatically quarantined like external/gate input — but
        dispatch is refused until this is set.
    """

    prompt: str
    confirmed_injection_risk: bool = False


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
    session_id = await service.start(
        body.prompt,
        confirmed_injection_risk=body.confirmed_injection_risk,
    )
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
    sid = await service.resume(
        session_id,
        body.prompt,
        confirmed_injection_risk=body.confirmed_injection_risk,
    )
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


@router.post("/sessions/{session_id}/poll", response_model=SessionSummary)
async def poll_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> SessionSummary:
    """
    Actively probe whether a session is still alive against its backend.

    :param session_id: Id of the session to probe.
    :param service: Session service, injected.
    :returns: The session's (possibly now-updated) summary.
    """
    return await service.poll(session_id)


def _last_event_id(request: Request) -> int:
    """Parse the ``Last-Event-ID`` header the browser sends on reconnect.

    :param request: The incoming request.
    :returns: The last sequence number the client saw, or 0 (replay
        everything) if the header is absent or not a valid integer.
    """
    raw = request.headers.get("last-event-id")
    try:
        return int(raw) if raw is not None else 0
    except ValueError:
        return 0


@router.get("/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    request: Request,
    service: SessionService = Depends(get_session_service),
) -> StreamingResponse:
    """
    Stream session events as Server-Sent Events.

    Honours ``Last-Event-ID`` so a browser reconnect only receives what
    it missed instead of the full history again.

    :param session_id: Id of the session to stream events for.
    :param request: The incoming request, for its ``Last-Event-ID``.
    :param service: Session service, injected.
    :returns: A streaming response of SSE event frames.
    """
    resume_after = _last_event_id(request)

    async def _frames() -> AsyncIterator[bytes]:
        async for item in service.stream(session_id, resume_after):
            if item is None:
                yield sse.KEEPALIVE
            else:
                sequence, payload = item
                yield sse.encode(payload, event_id=sequence)

    return StreamingResponse(
        _frames(), media_type="text/event-stream", headers=sse.HEADERS
    )
