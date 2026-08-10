"""Active liveness probing for the "force poll now" action.

Everything else in kestrel is push-based (SSE); this is the one place
that actively reaches out to a backend to ask "is this session really
still alive?" — for a session a backend's own event stream never
reported as finished (e.g. its remote process crashed silently).
"""
from __future__ import annotations

from app.backends.base import Backend, LivenessResult
from app.models import CanonicalEvent, EventKind
from app.storage.registry import SessionRegistry


async def poll_session(
    backend: Backend, registry: SessionRegistry, session_id: str
) -> LivenessResult:
    """Probe one session; record a diagnostic error and flip its status
    to "error" if the backend reports it's no longer alive.

    A no-op (``alive=True``) for an unknown session or a backend with
    nothing to check. Never downgrades a session that already looks
    fine, and never re-records once a session is already ``"error"``.
    """
    record = registry.get(session_id)
    if record is None:
        return LivenessResult(alive=True)
    result = await backend.check_alive(session_id)
    if not result.alive and record.status != "error":
        registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.RESULT,
                session_id=session_id,
                is_error=True,
                text=result.reason or "session no longer alive",
            ),
        )
        # append_event's own RESULT handling only ever flips to "idle" —
        # this is a confirmed-dead session, not a normal completion.
        registry.set_status(session_id, "error")
    return result
