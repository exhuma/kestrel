"""Tests for the notifications router (store mocked)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.main import create_app
from app.notifications import Notification
from app.persistence.notification_store import get_notification_store


class _FakeStore:
    def __init__(self) -> None:
        self.read_ids: list[int] = []

    def list_all(self) -> list[Notification]:
        return [
            Notification(
                id=2, workflow_id="wf-1", repo="o/r", issue_number=5,
                status="done", message="PR opened for o/r#5.",
                created_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
                read=False,
            ),
            Notification(
                id=1, workflow_id="wf-1", repo="o/r", issue_number=5,
                status="awaiting_plan_approval",
                message="Implementation plan ready for review: o/r#5.",
                created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
                read=True,
            ),
        ]

    def mark_read(self, notification_id: int) -> None:
        self.read_ids.append(notification_id)


def _client(store):
    app = create_app()
    app.dependency_overrides[get_notification_store] = lambda: store
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_list_notifications_newest_first() -> None:
    """Ensure the list endpoint returns the store's order and fields."""
    async with _client(_FakeStore()) as client:
        resp = await client.get("/api/notifications")
    assert resp.status_code == 200
    body = resp.json()
    assert [n["id"] for n in body] == [2, 1]
    assert body[0]["message"] == "PR opened for o/r#5."
    assert body[0]["read"] is False
    assert body[1]["read"] is True


@pytest.mark.asyncio
async def test_mark_read_calls_store() -> None:
    """Ensure marking a notification read reaches the store."""
    store = _FakeStore()
    async with _client(store) as client:
        resp = await client.post("/api/notifications/1/read")
    assert resp.status_code == 200
    assert store.read_ids == [1]


