"""Tests for the board intervention router (feature 026, T027)."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.models_board_records import SecurityReviewRecord
from app.services.board.bootstrap import get_quarantine_service


class _FakeQuarantine:
    def __init__(self) -> None:
        self.resolved: list[tuple[str, str]] = []

    def release(self, review_id: str) -> SecurityReviewRecord | None:
        if review_id == "missing":
            return None
        self.resolved.append((review_id, "released"))
        return SecurityReviewRecord(
            id=review_id,
            untrusted_input_id="input-1",
            card_id="card-1",
            workflow_id="wf-1",
            classification_category="prompt_injection",
            review_state="released",
            resolution="released",
        )

    def discard(self, review_id: str) -> SecurityReviewRecord | None:
        if review_id == "missing":
            return None
        self.resolved.append((review_id, "discarded"))
        return SecurityReviewRecord(
            id=review_id,
            untrusted_input_id="input-1",
            card_id="card-1",
            workflow_id="wf-1",
            classification_category="prompt_injection",
            review_state="discarded",
            resolution="discarded",
        )


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
