"""Tests for bearer-token validation and the auth_enabled short-circuit.

The JWKS *fetch* itself (``PyJWKClient.get_signing_key_from_jwt``) uses
``urllib`` internally, not ``httpx`` — so rather than mocking HTTP
transport, these tests monkeypatch ``get_jwks_client`` to return a fake
client that hands back a known test key. This still satisfies "never make
a real HTTP call to an identity provider in tests" (module-auth-oidc-python)
while testing exactly the validation logic this dependency owns.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from http import HTTPStatus

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import dependencies as auth_deps
from app.auth.dependencies import get_current_claims, require_permission
from app.auth.permissions import ALL_PERMISSIONS_SENTINEL
from app.config import Settings
from app.config_models import RoleMapping

_AUTHORITY = "https://idp.example.com/realms/kestrel"
_AUDIENCE = "kestrel-spa"


@dataclass
class _FakeSigningKey:
    key: object


class _FakeJWKClient:
    """Stands in for ``jwt.PyJWKClient`` — hands back a fixed test key
    instead of fetching one over the network."""

    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
        return _FakeSigningKey(key=self._public_key)


@pytest.fixture()
def rsa_keys():
    """A fresh RSA key pair for signing/validating test tokens."""
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    return private_key, private_key.public_key()


@pytest.fixture(autouse=True)
def _stub_jwks_client(monkeypatch: pytest.MonkeyPatch, rsa_keys) -> None:
    """Route every ``get_jwks_client`` call to the fake, keyed to the
    fixture's public key — no test needs a real JWKS fetch."""
    _, public_key = rsa_keys
    fake_client = _FakeJWKClient(public_key)
    monkeypatch.setattr(
        auth_deps, "get_jwks_client", lambda _authority: fake_client
    )


def _settings(**overrides) -> Settings:
    base = {
        "auth_enabled": True,
        "oidc_authority": _AUTHORITY,
        "oidc_audience": _AUDIENCE,
        "oidc_client_id": _AUDIENCE,
    }
    base.update(overrides)
    return Settings(**base)


def _token(private_key, **claim_overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-1",
        "email": "user@example.com",
        "preferred_username": "user",
        "iss": _AUTHORITY,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def _creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_auth_disabled_short_circuits_to_open_user() -> None:
    """auth_enabled=False needs no token and grants everything."""
    settings = Settings(auth_enabled=False)
    user = await get_current_claims(credentials=None, settings=settings)
    assert user.sub is None
    assert user.has("workflows:cleanup")


async def test_auth_disabled_ignores_a_present_but_bad_token() -> None:
    """Even a garbage token is irrelevant when auth is disabled."""
    settings = Settings(auth_enabled=False)
    user = await get_current_claims(
        credentials=_creds("not-a-real-token"), settings=settings
    )
    assert user.has("sessions:delete")


async def test_valid_token_resolves_identity_and_permissions(
    rsa_keys,
) -> None:
    """A well-formed, correctly-signed token resolves claims + permissions."""
    private_key, _ = rsa_keys
    mapping = RoleMapping(
        role="kestrel-admin", permissions=["workflows:cleanup"]
    )
    settings = _settings(role_mappings=[mapping])
    token = _token(private_key, realm_access={"roles": ["kestrel-admin"]})
    user = await get_current_claims(
        credentials=_creds(token), settings=settings
    )
    assert user.sub == "user-1"
    assert user.email == "user@example.com"
    assert user.permissions == frozenset({"workflows:cleanup"})
    assert ALL_PERMISSIONS_SENTINEL not in user.permissions


async def test_missing_token_is_401() -> None:
    """No Authorization header, auth enabled, is a clean 401."""
    settings = _settings()
    with pytest.raises(HTTPException) as exc_info:
        await get_current_claims(credentials=None, settings=settings)
    assert exc_info.value.status_code == HTTPStatus.UNAUTHORIZED


async def test_expired_token_is_401(rsa_keys) -> None:
    """An expired token is rejected."""
    private_key, _ = rsa_keys
    settings = _settings()
    token = _token(private_key, exp=int(time.time()) - 60)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_claims(
            credentials=_creds(token), settings=settings
        )
    assert exc_info.value.status_code == HTTPStatus.UNAUTHORIZED


async def test_wrong_audience_is_401(rsa_keys) -> None:
    """A token minted for a different audience is rejected."""
    private_key, _ = rsa_keys
    settings = _settings()
    token = _token(private_key, aud="some-other-client")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_claims(
            credentials=_creds(token), settings=settings
        )
    assert exc_info.value.status_code == HTTPStatus.UNAUTHORIZED


async def test_wrong_issuer_is_401(rsa_keys) -> None:
    """A token minted by a different issuer is rejected."""
    private_key, _ = rsa_keys
    settings = _settings()
    token = _token(private_key, iss="https://not-my-idp.example.com/x")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_claims(
            credentials=_creds(token), settings=settings
        )
    assert exc_info.value.status_code == HTTPStatus.UNAUTHORIZED


async def test_tampered_signature_is_401() -> None:
    """A token signed by a different key than the one JWKS reports fails."""
    other_private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048
    )
    settings = _settings()
    token = _token(other_private_key)  # signed with the WRONG key
    with pytest.raises(HTTPException) as exc_info:
        await get_current_claims(
            credentials=_creds(token), settings=settings
        )
    assert exc_info.value.status_code == HTTPStatus.UNAUTHORIZED


async def test_require_permission_allows_holder(rsa_keys) -> None:
    """require_permission passes a caller who holds the permission."""
    private_key, _ = rsa_keys
    mapping = RoleMapping(
        role="kestrel-admin", permissions=["workflows:cleanup"]
    )
    settings = _settings(role_mappings=[mapping])
    token = _token(private_key, realm_access={"roles": ["kestrel-admin"]})
    dependency = require_permission("workflows:cleanup")
    user = await get_current_claims(
        credentials=_creds(token), settings=settings
    )
    result = await dependency(user=user)
    assert result is user


async def test_require_permission_rejects_non_holder(rsa_keys) -> None:
    """require_permission 403s a validly-authenticated caller who lacks it."""
    private_key, _ = rsa_keys
    settings = _settings()  # no role_mappings at all
    token = _token(private_key, realm_access={"roles": ["kestrel-viewer"]})
    user = await get_current_claims(
        credentials=_creds(token), settings=settings
    )
    dependency = require_permission("workflows:cleanup")
    with pytest.raises(HTTPException) as exc_info:
        await dependency(user=user)
    assert exc_info.value.status_code == HTTPStatus.FORBIDDEN


async def test_require_permission_open_when_auth_disabled() -> None:
    """require_permission never blocks when auth is disabled."""
    settings = Settings(auth_enabled=False)
    user = await get_current_claims(credentials=None, settings=settings)
    dependency = require_permission("workflows:cleanup")
    result = await dependency(user=user)
    assert result is user
