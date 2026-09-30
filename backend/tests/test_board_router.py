"""Tests for the board intervention router (feature 026, T027)."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.models_board_records import SecurityReviewRecord
from app.persistence.board_quarantine_store import ReviewResolution
from app.services.board.bootstrap import get_quarantine_service


class _FakeQuarantine:
    def __init__(self, *, pending: bool = True) -> None:
        self.resolved: list[tuple[str, str]] = []
        self._pending = pending

    def release(self, review_id: str) -> ReviewResolution | None:
        return self._resolve(review_id, "released")

    def discard(self, review_id: str) -> ReviewResolution | None:
        return self._resolve(review_id, "discarded")

    def _resolve(
        self, review_id: str, resolution: str
    ) -> ReviewResolution | None:
        if review_id == "missing":
            return None
        self.resolved.append((review_id, resolution))
        review = SecurityReviewRecord(
            id=review_id,
            untrusted_input_id="input-1",
            card_id="card-1",
            workflow_id="wf-1",
            classification_category="prompt_injection",
            review_state=resolution,
            resolution=resolution,
        )
        return ReviewResolution(review, changed=self._pending)


def _client(quarantine) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_quarantine_service] = lambda: quarantine
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_release_resolves_the_review() -> None:
    quarantine = _FakeQuarantine()
    async with _client(quarantine) as client:
        resp = await client.post(
            "/api/board/security-reviews/review-1/resolve",
            json={"action": "release_quarantine"},
        )
    assert resp.status_code == httpx.codes.OK
    body = resp.json()
    assert body["review_state"] == "released"
    assert quarantine.resolved == [("review-1", "released")]


@pytest.mark.asyncio
async def test_discard_resolves_the_review() -> None:
    quarantine = _FakeQuarantine()
    async with _client(quarantine) as client:
        resp = await client.post(
            "/api/board/security-reviews/review-1/resolve",
            json={"action": "discard_quarantine"},
        )
    assert resp.status_code == httpx.codes.OK
    assert resp.json()["review_state"] == "discarded"
    assert quarantine.resolved == [("review-1", "discarded")]


@pytest.mark.asyncio
async def test_only_a_fresh_release_continues_the_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure releasing an already-resolved review continues nothing
    again (feature 041)."""
    continued: list[str] = []
    monkeypatch.setattr(
        "app.routers.board.schedule_intake_continuation", continued.append
    )
    for pending in (True, False):
        async with _client(_FakeQuarantine(pending=pending)) as client:
            resp = await client.post(
                "/api/board/security-reviews/review-1/resolve",
                json={"action": "release_quarantine"},
            )
        assert resp.status_code == httpx.codes.OK
    assert continued == ["wf-1"]


@pytest.mark.asyncio
async def test_unknown_review_is_404() -> None:
    quarantine = _FakeQuarantine()
    async with _client(quarantine) as client:
        resp = await client.post(
            "/api/board/security-reviews/missing/resolve",
            json={"action": "release_quarantine"},
        )
    assert resp.status_code == httpx.codes.NOT_FOUND


@pytest.mark.asyncio
async def test_response_never_carries_raw_content_fields() -> None:
    """The safe DTO has no field capable of holding raw suspect content."""
    quarantine = _FakeQuarantine()
    async with _client(quarantine) as client:
        resp = await client.post(
            "/api/board/security-reviews/review-1/resolve",
            json={"action": "release_quarantine"},
        )
    assert set(resp.json().keys()) == {
        "id",
        "card_id",
        "workflow_id",
        "classification_category",
        "reason",
        "review_state",
        "resolution",
    }
