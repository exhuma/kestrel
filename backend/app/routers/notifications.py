"""HTTP routes for the in-app notification center."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.persistence.notification_store import (
    NotificationStore,
    get_notification_store,
)
from app.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications")


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    store: NotificationStore = Depends(get_notification_store),
) -> list[NotificationOut]:
    """List all notifications, most recent first."""
    return [
        NotificationOut(
            id=n.id, workflow_id=n.workflow_id, repo=n.repo,
            issue_number=n.issue_number, status=n.status,
            message=n.message, created_at=n.created_at, read=n.read,
        )
        for n in store.list_all()
    ]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    store: NotificationStore = Depends(get_notification_store),
) -> dict[str, str]:
    """Mark one notification as read."""
    store.mark_read(notification_id)
    return {"status": "ok"}
