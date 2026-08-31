"""The request-scoped authenticated-identity value object.

Never persisted — constructed fresh on every request from validated token
claims plus the resolved permission set (feature 011). Kestrel owns no
``User`` table; see ``specs/011-oidc-authentication/research.md`` §4.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.auth.permissions import ALL_PERMISSIONS_SENTINEL


@dataclass(frozen=True)
class AuthenticatedUser:
    """One request's authenticated identity and resolved permissions.

    :param sub: The token's ``sub`` claim.
    :param email: The token's ``email`` claim, if present.
    :param preferred_username: The token's ``preferred_username`` claim,
        if present.
    :param permissions: The caller's resolved permission set (see
        :func:`app.auth.permissions.resolve_permissions`), or the
        "everything allowed" stand-in when auth is disabled.
    """

    sub: str | None
    email: str | None
    preferred_username: str | None
    permissions: frozenset[str]

    def has(self, permission: str) -> bool:
        """Whether this identity carries ``permission`` (or the
        "everything allowed" sentinel used when auth is disabled)."""
        return (
            ALL_PERMISSIONS_SENTINEL in self.permissions
            or permission in self.permissions
        )
