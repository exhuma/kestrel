"""HTTP routes for OIDC bootstrap, resolved permissions, and SSE tickets.

Kept separate from ``routers/identity.py`` (the oauth2-proxy-header
passthrough) deliberately — that router's docstring is explicit that its
headers are "never used for auth decisions"; mixing that trust model with
real token-validated auth in one handler would blur two different trust
boundaries for no benefit.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_claims
from app.auth.identity import AuthenticatedUser
from app.auth.tickets import mint
from app.config import Settings, get_settings
from app.schemas import AuthConfigOut, AuthPermissionsOut, TicketOut

router = APIRouter(prefix="/api/auth")


@router.get("/config", response_model=AuthConfigOut)
async def get_auth_config(
    settings: Settings = Depends(get_settings),
) -> AuthConfigOut:
    """
    The SPA's runtime OIDC bootstrap config.

    No authentication required — the SPA calls this *before* sign-in to
    learn whether it's even needed (see ``contracts/auth-config.md``).

    :param settings: Application settings, injected.
    :returns: ``enabled`` mirrors ``Settings.auth_enabled``; ``authority``/
        ``client_id`` are ``""`` when disabled.
    """
    if not settings.auth_enabled:
        return AuthConfigOut(enabled=False, authority="", client_id="")
    return AuthConfigOut(
        enabled=True,
        authority=settings.oidc_authority,
        client_id=settings.effective_oidc_client_id(),
    )


@router.get("/permissions", response_model=AuthPermissionsOut)
async def get_auth_permissions(
    user: AuthenticatedUser = Depends(get_current_claims),
) -> AuthPermissionsOut:
    """
    The caller's resolved identity + permission set.

    The single source of truth the frontend uses to decide which mutating
    controls to enable — see ``contracts/auth-permissions.md``. When auth
    is disabled, ``get_current_claims`` already resolves to the
    "everything allowed" stand-in (``permissions == {"*"}``), so no
    special-casing is needed here.

    :param user: The caller's identity/permissions, injected.
    :returns: ``sub``/``email``/``preferred_username`` are ``null`` when
        auth is disabled; ``permissions`` is ``["*"]`` in that case.
    """
    return AuthPermissionsOut(
        sub=user.sub,
        email=user.email,
        preferred_username=user.preferred_username,
        permissions=sorted(user.permissions),
    )


@router.post("/sse-ticket", response_model=TicketOut)
async def mint_sse_ticket(
    user: AuthenticatedUser = Depends(get_current_claims),
) -> TicketOut:
    """
    Mint a short-lived, single-use ticket for one of the four SSE streams.

    Requires normal bearer-token auth (called via the authenticated
    ``fetch``-based api client, never via ``EventSource`` itself — see
    ``contracts/auth-sse-ticket.md``).

    :param user: The caller's already-validated identity, injected.
    :returns: An opaque ticket, valid for ~30 seconds and one connection.
    """
    return TicketOut(ticket=mint(user))
