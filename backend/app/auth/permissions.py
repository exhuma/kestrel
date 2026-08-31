"""The fixed, app-owned permission vocabulary and its resolution.

Application code gates only on these permission strings, never on an
identity provider's role names directly (see :mod:`app.auth.roles` for the
IdP -> role-set half, and ``config_models.RoleMapping`` for the
operator-authored role -> permission mapping).

Leaf module: this file MUST NOT import :mod:`app.config` (or anything that
does). ``Settings._validate_role_mappings`` imports the vocabulary *from*
here to fail fast on an unknown permission string at startup; importing
``Settings`` back into this module would create a cycle the project's
import-linter contract forbids.
"""
from __future__ import annotations

from app.config_models import RoleMapping

#: One entry per genuinely consequential mutating action. Session `poll`
#: and notification mark-read are deliberately absent — they require only
#: authentication, never a specific permission (see
#: ``specs/011-oidc-authentication/data-model.md``).
PERMISSIONS = frozenset(
    {
        "sessions:write",
        "sessions:delete",
        "workflows:approve",
        "workflows:reject",
        "workflows:respond",
        "workflows:cleanup",
        "workflows:rerun",
        "workflows:delete",
    }
)

#: Sentinel returned by ``GET /api/auth/permissions`` when auth is
#: disabled, meaning "every permission" — see
#: ``contracts/auth-permissions.md``.
ALL_PERMISSIONS_SENTINEL = "*"


def resolve_permissions(
    roles: set[str], mappings: list[RoleMapping]
) -> frozenset[str]:
    """
    The union of permissions granted by every mapping whose role matches.

    :param roles: The caller's roles, as extracted from token claims (realm
        roles as-is, client roles namespaced — see
        :class:`app.auth.roles.RoleExtractor`).
    :param mappings: The operator-authored ``role_mappings`` config list.
    :returns: The resolved permission set. Empty when no mapping matches
        any of ``roles`` — a valid, expected state (view-only), not an
        error.
    """
    granted: set[str] = set()
    for mapping in mappings:
        if mapping.role in roles:
            granted.update(mapping.permissions)
    return frozenset(granted)
