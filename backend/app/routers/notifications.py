"""HTTP routes for the in-app notification center."""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app import sse
from app.notifications import Notification, signal_class
from app.persistence.notification_store import (
    NotificationStore,
    get_notification_store,
)
from app.schemas import NotificationOut
from app.storage.notification_bus import (
    NotificationBus,
    get_notification_bus,
)

router = APIRouter(prefix="/api/notifications")


def _to_out(n: Notification) -> NotificationOut:
    """Serialise a notification, deriving its signal class from status."""
    return NotificationOut(
        id=n.id, workflow_id=n.workflow_id, repo=n.repo,
        issue_number=n.issue_number, status=n.status,
        signal_class=signal_class(n.status),
        message=n.message, created_at=n.created_at, read=n.read,
    )


def _payload(store: NotificationStore) -> dict[str, object]:
    """Serialise the current notification list for an SSE frame."""
    return {
        "notifications": [
            _to_out(n).model_dump(mode="json") for n in store.list_all()
        ]
    }


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    store: NotificationStore = Depends(get_notification_store),
) -> list[NotificationOut]:
    """List all notifications, most recent first."""
    return [_to_out(n) for n in store.list_all()]


@router.get("/events")
async def stream_notifications(
    store: NotificationStore = Depends(get_notification_store),
    bus: NotificationBus = Depends(get_notification_bus),
) -> StreamingResponse:
    """
    Stream the notification list as Server-Sent Events.

    Emits the current list immediately, then a fresh list on every
    change (a new notification, or one marked read) — replacing the old
    5-second poll.
    """

    async def _frames() -> AsyncIterator[bytes]:
        q = bus.subscribe()
        try:
            yield sse.encode(_payload(store))
            async for tick in sse.with_heartbeat(q):
                if tick is None:
                    yield sse.KEEPALIVE
                else:
                    yield sse.encode(_payload(store))
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        _frames(), media_type="text/event-stream", headers=sse.HEADERS
    )


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    store: NotificationStore = Depends(get_notification_store),
    bus: NotificationBus = Depends(get_notification_bus),
) -> dict[str, str]:
    """Mark one notification as read."""
    store.mark_read(notification_id)
    bus.publish()
    return {"status": "ok"}
