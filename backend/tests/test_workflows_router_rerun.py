"""Tests for POST /api/workflows/{id}/rerun (feature 008, service mocked).

Split out from test_workflows_router.py rather than added there to keep
both files under the module-length limit; reuses that module's shared
``_client``/``_FakeService`` test doubles (established cross-test-module
pattern — see e.g. test_poll_source.py importing from test_jira_poll.py).
"""
from __future__ import annotations

import pytest

from tests.test_workflows_router import _client, _FakeService

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_FORBIDDEN = 403


@pytest.mark.asyncio
async def test_rerun_workflow_ok() -> None:
    """Ensure POST /api/workflows/{id}/rerun returns the new run's id."""
    service = _FakeService()
    async with _client(service) as client:
        resp = await client.post("/api/workflows/wf-1/rerun")
    assert resp.status_code == _HTTP_OK
    assert resp.json()["workflow_id"] == "wf-2"
    assert service.reran == "wf-1"


@pytest.mark.asyncio
async def test_rerun_unknown_workflow_returns_404() -> None:
    """Ensure rerunning an unknown workflow maps to HTTP 404."""
    async with _client(_FakeService()) as client:
        resp = await client.post("/api/workflows/nope/rerun")
    assert resp.status_code == _HTTP_NOT_FOUND


@pytest.mark.asyncio
async def test_rerun_public_source_returns_403() -> None:
    """Ensure a rerun refusal (public task source) maps to HTTP 403."""
    async with _client(_FakeService()) as client:
        resp = await client.post("/api/workflows/wf-public/rerun")
    assert resp.status_code == _HTTP_FORBIDDEN
    assert resp.json() == {
        "detail": "rerun is not available for this workflow's task source"
    }
