"""The activity reaches the board API (feature 033)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard
from app.services.board.live_activity import get_live_activity
from tests.test_board_router_views import _client


@pytest.mark.asyncio
async def test_live_work_shows_as_working_on_both_views(
    tmp_path: Path,
) -> None:
    """Ensure the listing and the snapshot agree, and name the card."""
    client, store, _claims = _client(tmp_path)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="understanding",
            title="Restate the request", state="claimed",
            eligible_roles=("developer",),
        )
    )

    with get_live_activity().track(
        "wf-1", "Engineering", "Restate the request"
    ):
        async with client as c:
            listing = (await c.get("/api/board/workflows")).json()
            snapshot = (await c.get("/api/board/workflows/wf-1/board")).json()

    for activity in (listing[0]["activity"], snapshot["activity"]):
        assert activity["state"] == "working"
        assert activity["subject"] == "Restate the request"
        assert activity["since"] is not None


@pytest.mark.asyncio
async def test_after_the_work_stops_it_is_not_working(
    tmp_path: Path,
) -> None:
    """Ensure a claim with nothing running reads as stalled (SC-002)."""
    client, store, _claims = _client(tmp_path)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="understanding",
            title="Restate the request", state="claimed",
            eligible_roles=("developer",),
        )
    )

    async with client as c:
        snapshot = (await c.get("/api/board/workflows/wf-1/board")).json()

    assert snapshot["activity"]["state"] == "stalled"
    assert snapshot["activity"]["reason"] == "interrupted_claim"
