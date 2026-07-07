"""Shared-secret bearer gate for the ``/api`` surface.

Kestrel drives an agent that runs shell commands and holds a write-scoped
GitHub token, so an unauthenticated API is a remote trigger for that
capability. This dependency gates every ``/api/*`` route behind a single
shared secret (``KESTREL_API_TOKEN``).

It is deliberately *not* multi-user auth: one secret, constant-time
compared. When no token is configured the gate is open (the dev default),
and the server separately refuses to bind a non-loopback interface so an
open API is never exposed off-host.
"""
from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status

from app.config import Settings, get_settings


def _present_token(request: Request) -> str | None:
    """Extract a caller-supplied token from the request, if any.

    Prefers the ``Authorization: Bearer <token>`` header. Falls back to an
    ``access_token`` query parameter so that SSE ``EventSource`` clients —
    which cannot set request headers — can still authenticate.
    """
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[len("Bearer ") :].strip()
    return request.query_params.get("access_token")


async def require_token(
    request: Request, settings: Settings = Depends(get_settings)
) -> None:
    """Reject requests lacking the configured API token.

    A no-op when ``api_token`` is unset (open dev mode). Otherwise compares
    the presented token to the configured one in constant time and raises
    HTTP 401 on any mismatch or absence.

    :raises HTTPException: 401 when a token is required but not matched.
    """
    expected = settings.api_token
    if not expected:
        return
    presented = _present_token(request)
    if presented is None or not hmac.compare_digest(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
