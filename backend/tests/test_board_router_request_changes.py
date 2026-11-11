"""Tests for the route that sends delivered work back for more changes."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.persistence.board_store import BoardStore
from tests.test_board_router_views import _client, _ready_card

pytestmark = pytest.mark.integration


def _deliver(store: BoardStore) -> None:
    store.create_card(_ready_card("delivery", kind="delivery", state="done"))


def _changes(revision: int, feedback: str = "Rename the button") -> dict:
    return {"feedback": feedback, "expected_revision": revision}


@pytest.mark.asyncio
async def test_request_changes_reopens_a_delivered_request(
    tmp_path: Path,
) -> None:
    """Ensure the route starts the work and the board shows it."""
    client, store, _ = _client(tmp_path)
    _deliver(store)
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/request-changes",
            json=_changes(store.get_workflow("wf-1").revision),
        )
        board = (await c.get("/api/board/workflows/wf-1/board")).json()

    assert resp.status_code == httpx.codes.OK
    assert board["outcome"] == "in_progress"
    assert resp.json()["card_id"] in {
        card["id"] for card in board["cards"] if card["state"] == "ready"
    }


@pytest.mark.asyncio
async def test_request_changes_says_why_it_was_refused(tmp_path: Path) -> None:
    """Ensure a refusal is a 422 the page can show as it is."""
    client, store, _ = _client(tmp_path)
    _deliver(store)
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/request-changes",
            json=_changes(store.get_workflow("wf-1").revision, feedback="  "),
        )

    assert resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY
    assert resp.json()["detail"] == "say what should change"


@pytest.mark.asyncio
async def test_request_changes_refuses_a_stale_board(tmp_path: Path) -> None:
    """Ensure feedback on an out-of-date view is a conflict."""
    client, store, _ = _client(tmp_path)
    _deliver(store)
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/wf-1/request-changes",
            json=_changes(store.get_workflow("wf-1").revision + 1),
        )

    assert resp.status_code == httpx.codes.CONFLICT


@pytest.mark.asyncio
async def test_request_changes_on_an_unknown_request_is_404(
    tmp_path: Path,
) -> None:
    """Ensure a wrong address is not mistaken for a refusal."""
    client, _, _ = _client(tmp_path)
    async with client as c:
        resp = await c.post(
            "/api/board/workflows/missing/request-changes", json=_changes(1)
        )

    assert resp.status_code == httpx.codes.NOT_FOUND
