"""Tests for the dev-only reset routes (feature 026, T069).

Temporary, per ``app/routers/board_dev.py``'s own module docstring.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.main import create_app
from app.models_board import Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore, get_board_store
from app.services.board.bootstrap import (
    get_board_service,
    get_claims_service,
    get_workspace_service,
)
from app.services.board.claims import ClaimsService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.board.workspace import WorkspaceService
from tests.board_test_support import board_session_factory

_WORKFLOW = Workflow(
    id="wf-1", source="local", task_ref="local/task-1", repo="owner/repo",
    base_branch="main", source_visibility="private", title="Try a thing",
)


def _enabled_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KESTREL_BOARD_DEV_ACTIONS_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    claims = ClaimsService(
        store=store, claims_store=BoardClaimsStore(factory),
        roster=SpecialistRoster({}), max_parallel_read_cards=4,
        default_lease_seconds=60, default_workspace_lease_seconds=600,
    )
    workspace = WorkspaceService(str(tmp_path / "root"))
    app.dependency_overrides[get_board_store] = lambda: store
    app.dependency_overrides[get_board_service] = lambda: board_service
    app.dependency_overrides[get_claims_service] = lambda: claims
    app.dependency_overrides[get_workspace_service] = lambda: workspace
    return app, store


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_the_routes_do_not_exist_when_disabled() -> None:
    app = create_app()
    async with _client(app) as client:
        resp = await client.post("/api/board/workflows/wf-1/dev/cleanup")
    assert resp.status_code == httpx.codes.NOT_FOUND


@pytest.mark.asyncio
async def test_cleanup_returns_204_for_a_known_private_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, store = _enabled_app(tmp_path, monkeypatch)
    store.create_workflow(_WORKFLOW)

    async with _client(app) as client:
        resp = await client.post("/api/board/workflows/wf-1/dev/cleanup")

    assert resp.status_code == httpx.codes.NO_CONTENT


@pytest.mark.asyncio
async def test_rerun_returns_422_for_an_unknown_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _store = _enabled_app(tmp_path, monkeypatch)

    async with _client(app) as client:
        resp = await client.post("/api/board/workflows/wf-missing/dev/rerun")

    assert resp.status_code == httpx.codes.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_rerun_reopens_a_known_private_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, store = _enabled_app(tmp_path, monkeypatch)
    store.create_workflow(_WORKFLOW)

    async with _client(app) as client:
        resp = await client.post("/api/board/workflows/wf-1/dev/rerun")

    assert resp.status_code == httpx.codes.NO_CONTENT
    gates = [
        c for c in store.list_cards("wf-1") if c.kind == "understanding_gate"
    ]
    assert len(gates) == 1
