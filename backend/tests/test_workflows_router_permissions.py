"""Tests for permission-gating on the workflows router (User Story 2).

Split from test_workflows_router_auth.py (which covers User Story 1's
authenticated-only tier) to keep each file focused and under the
module-length limit; reuses test_workflows_router.py's shared
``_FakeService`` (see test_workflows_router_rerun.py for the established
cross-test-module precedent).
"""
from __future__ import annotations

import httpx
import pytest

from app.config import get_settings
from app.main import create_app
from app.services.workflows import get_workflow_service
from tests.conftest import _auth_enabled_settings, override_auth
from tests.test_workflows_router import _FakeService

_HTTP_OK = 200
_HTTP_CONFLICT = 409
_HTTP_FORBIDDEN = 403

# (method, path, the one permission that gates it, a body satisfying that
# route's own schema, the status once the permission check passes) — per
# contracts/permission-gated-endpoints.md. Every fake .reply() call
# unconditionally raises InvalidWorkflowStateError (see
# test_workflows_router.py's _FakeService, shared with its own conflict
# test) — 409 there still proves the permission check passed and the
# request reached the service layer, which is what this table checks.
_GATED_ACTIONS = [
    ("DELETE", "/api/workflows/wf-1", "workflows:delete", None, _HTTP_OK),
    (
        "POST", "/api/workflows/wf-1/cleanup", "workflows:cleanup", None,
        _HTTP_OK,
    ),
    ("POST", "/api/workflows/wf-1/rerun", "workflows:rerun", None, _HTTP_OK),
    (
        "POST", "/api/workflows/wf-1/approve", "workflows:approve", {},
        _HTTP_OK,
    ),
    ("POST", "/api/workflows/wf-1/reject", "workflows:reject", {}, _HTTP_OK),
    (
        "POST", "/api/workflows/wf-1/reply", "workflows:respond",
        {"text": "ok"}, _HTTP_CONFLICT,
    ),
    (
        "POST", "/api/workflows/wf-1/answers", "workflows:respond",
        {"answers": {}}, _HTTP_OK,
    ),
    (
        "POST", "/api/workflows/wf-1/answers/draft", "workflows:respond",
        {"answers": {}}, _HTTP_OK,
    ),
]


def _client(service, permissions: frozenset[str] | None) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_workflow_service] = lambda: service
    app.dependency_overrides[get_settings] = _auth_enabled_settings
    override_auth(app, permissions=permissions)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


_METHOD_PATH_BODY = [(m, p, b) for m, p, _, b, _s in _GATED_ACTIONS]


@pytest.mark.parametrize(("method", "path", "body"), _METHOD_PATH_BODY)
@pytest.mark.asyncio
async def test_gated_action_requires_its_permission(
    method: str, path: str, body: dict | None
) -> None:
    """Each gated action 403s for an authenticated caller lacking it."""
    async with _client(_FakeService(), frozenset()) as client:
        resp = await client.request(method, path, json=body)
    assert resp.status_code == _HTTP_FORBIDDEN


@pytest.mark.parametrize(
    ("method", "path", "permission", "body", "expected"), _GATED_ACTIONS
)
@pytest.mark.asyncio
async def test_gated_action_ok_with_its_permission(
    method: str, path: str, permission: str, body: dict | None,
    expected: int,
) -> None:
    """Each gated action passes the permission check for a caller holding
    it — reaching the service layer rather than being refused at 403."""
    async with _client(_FakeService(), frozenset({permission})) as client:
        resp = await client.request(method, path, json=body)
    assert resp.status_code == expected
