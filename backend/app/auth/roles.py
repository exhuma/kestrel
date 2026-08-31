"""Pluggable IdP role extraction: claims dict -> a set of role names.

One :class:`RoleExtractor` per identity provider, selected by
``Settings.oidc_provider`` via the registry below — mirrors the existing
``TaskSource``/``Backend`` protocol+registry pattern already in this
codebase (``app/ports.py``, ``app/backends/registry.py``): a new IdP is one
new adapter class plus one registry entry, never a redesign of the
permission model (spec FR-012).
"""
from __future__ import annotations

from typing import Protocol


class RoleExtractor(Protocol):
    """Extracts the caller's role names from validated OIDC claims."""

    def extract_roles(self, claims: dict, client_id: str) -> set[str]:
        """
        :param claims: The validated token payload.
        :param client_id: The client whose client-scoped roles to include
            (``Settings.effective_oidc_client_id()``).
        :returns: The caller's role names — realm-wide roles as reported,
            client-scoped roles namespaced (see
            :class:`KeycloakRoleExtractor`).
        """
        ...


class KeycloakRoleExtractor:
    """Reads Keycloak's ``realm_access``/``resource_access`` claim shape.

    Realm roles (``realm_access.roles``) are used as-is. Client roles
    (``resource_access[client_id].roles``) are namespaced as
    ``f"{client_id}:{role}"`` before being added to the result, so a
    client role can never collide with a same-named realm role — an
    operator's ``role_mappings`` entry for a client role is written using
    that same namespaced form.
    """

    def extract_roles(self, claims: dict, client_id: str) -> set[str]:
        """See :meth:`RoleExtractor.extract_roles`."""
        realm_roles = set(claims.get("realm_access", {}).get("roles", []))
        client_roles = {
            f"{client_id}:{role}"
            for role in claims.get("resource_access", {})
            .get(client_id, {})
            .get("roles", [])
        }
        return realm_roles | client_roles


#: Provider name (``Settings.oidc_provider``) -> extractor instance.
_REGISTRY: dict[str, RoleExtractor] = {
    "keycloak": KeycloakRoleExtractor(),
}


def get_role_extractor(provider: str) -> RoleExtractor:
    """
    The configured :class:`RoleExtractor` for ``provider``.

    :param provider: ``Settings.oidc_provider``.
    :raises ValueError: If ``provider`` has no registered extractor.
    """
    try:
        return _REGISTRY[provider]
    except KeyError:
        valid = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"unknown oidc_provider {provider!r}; valid providers: {valid}"
        ) from None
