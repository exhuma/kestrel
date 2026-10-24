"""A failed request is never hidden as finished (feature 040)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard
from tests.test_board_router_views import _client


def _add(store, card_id: str, kind: str, state: str) -> None:
    store.create_card(WorkCard(
        id=card_id, workflow_id="wf-1", kind=kind, title=kind, state=state,
    ))


async def _default_listing(client) -> list[dict]:
    async with client as c:
        return (await c.get("/api/board/workflows")).json()


@pytest.mark.asyncio
async def test_a_failed_request_stays_listed_as_failed(tmp_path: Path) -> None:
    """Reproduces wf-36ca7a1a: all terminal, one failed card."""
    client, store, _claims = _client(tmp_path)
    _add(store, "s", "security_review", "done")
    _add(store, "dev", "refinement", "done")
    _add(store, "pm", "refinement", "failed")

    (row,) = await _default_listing(client)

    assert (row["outcome"], row["phase"], row["stage"]) == (
        "failed", "Pre-assessment", "Discovery",
    )
    assert row["activity"]["state"] == "problem"


@pytest.mark.asyncio
async def test_a_delivered_request_is_done_and_hidden(tmp_path: Path) -> None:
    client, store, _claims = _client(tmp_path)
    _add(store, "d", "delivery", "done")

    assert await _default_listing(client) == []


@pytest.mark.asyncio
async def test_a_stopped_request_is_cancelled_and_hidden(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    _add(store, "c1", "cab1_gate", "cancelled")

    async with client as c:
        default = (await c.get("/api/board/workflows")).json()
        (row,) = (await c.get(
            "/api/board/workflows", params={"include_completed": "true"}
        )).json()

    assert default == []
    assert (row["outcome"], row["phase"], row["stage"]) == (
        "cancelled", "cancelled", "Cancelled",
    )
    assert row["activity"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_the_snapshot_carries_the_outcome_and_spine(
    tmp_path: Path,
) -> None:
    client, store, _claims = _client(tmp_path)
    _add(store, "pm", "refinement", "failed")

    async with client as c:
        body = (await c.get("/api/board/workflows/wf-1/board")).json()

    assert body["outcome"] == "failed"
    statuses = {p["name"]: p["status"] for p in body["phases"]}
    assert statuses["Pre-assessment"] == "problem"
    assert statuses["Delivery"] == "upcoming"
