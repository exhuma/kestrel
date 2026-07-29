"""HTTP route exposing the oauth2-proxy-forwarded identity."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas import IdentityOut

router = APIRouter(prefix="/api/identity")


@router.get("", response_model=IdentityOut)
async def get_identity(request: Request) -> IdentityOut:
    """Return the identity oauth2-proxy forwarded for this request.

    Fields are ``null`` when the corresponding header is absent (no
    reverse proxy in front, e.g. local dev) — kestrel does not perform
    authentication itself, it only surfaces what was already forwarded.
    """
    return IdentityOut(
        username=request.headers.get("X-Forwarded-User"),
        email=request.headers.get("X-Forwarded-Email"),
        preferred_username=request.headers.get(
            "X-Forwarded-Preferred-Username"
        ),
    )
