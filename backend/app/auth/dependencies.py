"""FastAPI dependencies: bearer-token validation and permission gating.

``get_current_claims`` is both the "authenticated-only" dependency (use it
directly) and the base ``require_permission(...)`` builds on. Both
short-circuit to an "everything allowed" identity when
``Settings.auth_enabled`` is false, so every existing route keeps working
with zero config changes (feature 011).
"""
from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import tickets
from app.auth.identity import AuthenticatedUser
from app.auth.jwks import get_jwks_client
from app.auth.permissions import ALL_PERMISSIONS_SENTINEL, resolve_permissions
from app.auth.roles import get_role_extractor
from app.config import Settings, get_settings

#: ``auto_error=False`` so a missing header is handled explicitly below
#: (a uniform 401, not FastAPI's default 403 "Not authenticated").
_bearer = HTTPBearer(auto_error=False)


def _open_user() -> AuthenticatedUser:
    """The stand-in identity used when auth is disabled: everything
    allowed, no claims to report."""
    return AuthenticatedUser(
        sub=None,
        email=None,
        preferred_username=None,
        permissions=frozenset({ALL_PERMISSIONS_SENTINEL}),
    )


async def get_current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """
    Validate the bearer token and resolve the caller's identity/permissions.

    This is also the "authenticated-only" dependency: any validly
    authenticated caller passes, regardless of their permission set — use
    it directly on routes that require sign-in but no specific permission.

    :param credentials: The ``Authorization: Bearer`` header, if present.
    :param settings: Application settings, injected.
    :returns: The "everything allowed" stand-in when ``auth_enabled`` is
        false; otherwise the caller's validated identity.
    :raises HTTPException: 401 when auth is enabled and the token is
        missing or fails validation (expired, wrong ``aud``/``iss``,
        tampered signature). The underlying exception is never exposed to
        the client.
    """
    if not settings.auth_enabled:
        return _open_user()
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing bearer token")

    try:
        client = get_jwks_client(settings.oidc_authority)
        signing_key = client.get_signing_key_from_jwt(credentials.credentials)
        payload = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.effective_oidc_issuer(),
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc

    extractor = get_role_extractor(settings.oidc_provider)
    roles = extractor.extract_roles(
        payload, settings.effective_oidc_client_id()
    )
    permissions = resolve_permissions(roles, settings.role_mappings)
    return AuthenticatedUser(
        sub=payload.get("sub"),
        email=payload.get("email"),
        preferred_username=payload.get("preferred_username"),
        permissions=permissions,
    )


async def get_ticket_claims(
    ticket: str | None = None,
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """
    Authenticate an ``/events`` (SSE) connection via a minted ticket.

    Browser ``EventSource`` cannot set an ``Authorization`` header, so the
    four live-updating streams use this instead of :func:`get_current_claims`
    — see ``POST /api/auth/sse-ticket`` and :mod:`app.auth.tickets`.

    :param ticket: The ``?ticket=...`` query parameter.
    :param settings: Application settings, injected.
    :returns: The "everything allowed" stand-in when ``auth_enabled`` is
        false; otherwise the ticket's embedded identity.
    :raises HTTPException: 401 when auth is enabled and the ticket is
        missing, malformed, expired, or already used.
    """
    if not settings.auth_enabled:
        return _open_user()
    user = tickets.validate(ticket) if ticket else None
    if user is None:
        raise HTTPException(status_code=401, detail="invalid ticket")
    return user


def require_permission(permission: str):
    """
    A dependency factory gating a route behind one permission.

    :param permission: A string from :data:`app.auth.permissions.PERMISSIONS`.
    :returns: A dependency that resolves to the caller's
        :class:`AuthenticatedUser` on success.
    """

    async def _dependency(
        user: AuthenticatedUser = Depends(get_current_claims),
    ) -> AuthenticatedUser:
        if not user.has(permission):
            raise HTTPException(
                status_code=403,
                detail=f"missing permission: {permission}",
            )
        return user

    return _dependency
