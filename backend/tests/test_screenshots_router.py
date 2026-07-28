"""Tests for the screenshots router (service + settings overridden)."""
from __future__ import annotations

import os
from http import HTTPStatus

import httpx
import pytest

from app.config import Settings, get_settings
from app.main import create_app
from app.models_workflow import WorkflowRun
from app.services.exceptions import WorkflowNotFoundError
from app.services.workflows import get_workflow_service


class _FakeService:
    def __init__(self, run: WorkflowRun) -> None:
        self._run = run

    def get(self, workflow_id: str) -> WorkflowRun:
        if workflow_id != self._run.id:
            raise WorkflowNotFoundError(workflow_id)
        return self._run


def _seed(tmp_path) -> WorkflowRun:
    run = WorkflowRun(
        id="wf-1", repo="o/r", workspace=str(tmp_path),
        artifact_dir=".kestrel/2026-07-28-001",
    )
    stage = os.path.join(
        str(tmp_path), run.artifact_dir, "screenshots", "verify"
    )
    os.makedirs(stage, exist_ok=True)
    with open(os.path.join(stage, "ok.png"), "wb") as handle:
        handle.write(b"\x89PNGdata")
    return run


def _client(run: WorkflowRun, durable: str):
    app = create_app()
    app.dependency_overrides[get_workflow_service] = lambda: _FakeService(run)
    app.dependency_overrides[get_settings] = lambda: Settings(
        screenshots_root=durable
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_list_returns_urls(tmp_path) -> None:
    """Ensure the list endpoint returns each shot with its serve URL."""
    run = _seed(tmp_path)
    async with _client(run, str(tmp_path / "d")) as client:
        resp = await client.get("/api/workflows/wf-1/screenshots")
    assert resp.status_code == HTTPStatus.OK
    assert resp.json() == [
        {
            "name": "ok.png", "stage": "verify",
            "url": "/api/workflows/wf-1/screenshots/verify/ok.png",
        }
    ]


@pytest.mark.asyncio
async def test_get_serves_image_bytes(tmp_path) -> None:
    """Ensure the file endpoint returns the bytes with an image type."""
    run = _seed(tmp_path)
    async with _client(run, str(tmp_path / "d")) as client:
        resp = await client.get(
            "/api/workflows/wf-1/screenshots/verify/ok.png"
        )
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == b"\x89PNGdata"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/workflows/wf-1/screenshots/verify/missing.png",
        "/api/workflows/wf-1/screenshots/bogus/ok.png",
        "/api/workflows/wf-1/screenshots/verify/notes.txt",
    ],
)
async def test_get_invalid_is_404(tmp_path, path) -> None:
    """Ensure missing/unknown-stage/non-image requests 404."""
    run = _seed(tmp_path)
    async with _client(run, str(tmp_path / "d")) as client:
        resp = await client.get(path)
    assert resp.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_unknown_run_is_404(tmp_path) -> None:
    """Ensure an unknown workflow id 404s before any file work."""
    run = _seed(tmp_path)
    async with _client(run, str(tmp_path / "d")) as client:
        resp = await client.get("/api/workflows/nope/screenshots")
    assert resp.status_code == HTTPStatus.NOT_FOUND
