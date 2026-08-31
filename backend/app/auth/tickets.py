"""Short-lived, single-use SSE connection tickets (feature 011).

Browser ``EventSource`` cannot set an ``Authorization`` header, so the four
live-updating streams authenticate via a ticket instead: mint one via
``POST /api/auth/sse-ticket`` (normal bearer-token auth), then pass it as
``?ticket=...`` on the stream URL. The ticket is only needed to establish
the connection — signed with an in-process secret (kestrel's own minted
credential, unrelated to the IdP's keys), ~30s TTL, and rejected on reuse.
"""
from __future__ import annotations

import secrets
import time
import uuid

import jwt

from app.auth.identity import AuthenticatedUser

_TICKET_TTL_SECONDS = 30
#: In-process signing secret, generated once at import time. Tickets are
#: meaningless after ~30s, so this has no need to survive a restart or be
#: shared across processes.
_SECRET = secrets.token_bytes(32)
#: jti -> expiry (unix ts), enforcing one-time use. Bounded: pruned on
#: every call, so it never holds more than "tickets minted in the last
#: ~30s" (consistent with kestrel's existing in-memory-registry pattern).
_used_jtis: dict[str, float] = {}


def mint(user: AuthenticatedUser) -> str:
    """
    Mint a ~30s, single-use ticket carrying ``user``'s identity.

    :param user: The caller's already-authenticated identity (from
        ``get_current_claims`` on the minting request).
    :returns: A compact, HS256-signed ticket.
    """
    claims = {
        "sub": user.sub,
        "permissions": sorted(user.permissions),
        "exp": time.time() + _TICKET_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _SECRET, algorithm="HS256")


def validate(ticket: str) -> AuthenticatedUser | None:
    """
    Validate a ticket: signature, expiry, and one-time use.

    :param ticket: The ``?ticket=...`` value from an ``/events`` request.
    :returns: The embedded identity on success; ``None`` on any failure
        (malformed, tampered, expired, or a replayed ``jti``) — the caller
        maps that to a rejected connection.
    """
    _prune_expired()
    try:
        claims = jwt.decode(ticket, _SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    jti = claims.get("jti")
    if not jti or jti in _used_jtis:
        return None
    _used_jtis[jti] = claims["exp"]
    return AuthenticatedUser(
        sub=claims.get("sub"),
        email=None,
        preferred_username=None,
        permissions=frozenset(claims.get("permissions", [])),
    )


def _prune_expired() -> None:
    now = time.time()
    for jti in [j for j, exp in _used_jtis.items() if exp < now]:
        del _used_jtis[jti]
