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
from app.schemas import AuthConfigOut, TicketOut

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
