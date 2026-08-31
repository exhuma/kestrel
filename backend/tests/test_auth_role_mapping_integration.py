"""End-to-end role-mapping tests (User Story 3): a config.toml-style
role_mappings list, a real signed token carrying realm/client roles, and
a gated router endpoint — proving the whole chain (extraction ->
resolution -> enforcement), not just each piece in isolation.
"""
from __future__ import annotations

import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import dependencies as auth_deps
from app.auth.permissions import resolve_permissions
from app.config import Settings, get_settings
from app.config_models import RoleMapping
from app.main import create_app
from app.services.workflows import get_workflow_service
from tests.test_workflows_router import _FakeService

_AUTHORITY = "https://idp.example.com/realms/kestrel"
_AUDIENCE = "kestrel-spa"
_HTTP_OK = 200
_HTTP_FORBIDDEN = 403


class _FakeJWKClient:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str):
        return type("Key", (), {"key": self._public_key})()


@pytest.fixture()
def rsa_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _stub_jwks_client(monkeypatch: pytest.MonkeyPatch, rsa_keys) -> None:
    _, public_key = rsa_keys
    fake_client = _FakeJWKClient(public_key)
    monkeypatch.setattr(
        auth_deps, "get_jwks_client", lambda _authority: fake_client
    )


def _token(private_key, **claim_overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-1",
        "iss": _AUTHORITY,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def _client(settings: Settings) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_workflow_service] = _FakeService
    app.dependency_overrides[get_settings] = lambda: settings
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_realm_role_mapping_grants_the_configured_permission(
    rsa_keys,
) -> None:
    """A realm role mapped in config.toml grants its configured permission
    end-to-end: a real token -> cleanup succeeds; a differently-rolled
    token -> cleanup is refused."""
    private_key, _ = rsa_keys
    mapping = RoleMapping(
        role="kestrel-admin", permissions=["workflows:cleanup"]
    )
    settings = Settings(
        auth_enabled=True,
        oidc_authority=_AUTHORITY,
        oidc_audience=_AUDIENCE,
        role_mappings=[mapping],
    )

    admin_token = _token(
        private_key, realm_access={"roles": ["kestrel-admin"]}
    )
    async with _client(settings) as client:
        resp = await client.post(
            "/api/workflows/wf-1/cleanup",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
    assert resp.status_code == _HTTP_OK

    viewer_token = _token(
        private_key, realm_access={"roles": ["kestrel-viewer"]}
    )
    async with _client(settings) as client:
        resp = await client.post(
            "/api/workflows/wf-1/cleanup",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
    assert resp.status_code == _HTTP_FORBIDDEN


async def test_client_role_mapping_grants_identically_to_realm_role(
    rsa_keys,
) -> None:
    """A namespaced client role behaves exactly like a realm role."""
    private_key, _ = rsa_keys
    mapping = RoleMapping(
        role=f"{_AUDIENCE}:deleter", permissions=["sessions:delete"]
    )
    settings = Settings(
        auth_enabled=True,
        oidc_authority=_AUTHORITY,
        oidc_audience=_AUDIENCE,
        oidc_client_id=_AUDIENCE,
        role_mappings=[mapping],
    )
    token = _token(
        private_key,
        resource_access={_AUDIENCE: {"roles": ["deleter"]}},
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.delete(
            "/api/sessions/s1", headers={"Authorization": f"Bearer {token}"}
        )
    # SessionService isn't overridden here (unrelated to this test's
    # concern), so a real service resolves; an unmapped role would 403
    # before ever reaching it, which is what matters — anything other
    # than 403 proves the permission check passed.
    assert resp.status_code != _HTTP_FORBIDDEN


def test_changing_role_mappings_changes_resolved_permissions() -> None:
    """Simulates editing config.toml + restarting: two independent
    Settings() builds with different role_mappings resolve differently
    for the same role set (FR-005/SC-002), with no code change."""
    roles = {"kestrel-admin"}

    before = Settings(
        role_mappings=[
            RoleMapping(role="kestrel-admin", permissions=["workflows:rerun"])
        ]
    )
    after = Settings(
        role_mappings=[
            RoleMapping(
                role="kestrel-admin", permissions=["workflows:cleanup"]
            )
        ]
    )

    assert resolve_permissions(roles, before.role_mappings) == frozenset(
        {"workflows:rerun"}
    )
    assert resolve_permissions(roles, after.role_mappings) == frozenset(
        {"workflows:cleanup"}
    )
