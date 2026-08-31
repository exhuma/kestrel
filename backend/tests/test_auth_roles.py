"""Tests for pluggable IdP role extraction (app.auth.roles)."""
from __future__ import annotations

import pytest

from app.auth.roles import KeycloakRoleExtractor, get_role_extractor


def test_extracts_realm_roles_as_is() -> None:
    """Realm roles are used verbatim, no namespacing."""
    claims = {"realm_access": {"roles": ["kestrel-admin", "offline_access"]}}
    roles = KeycloakRoleExtractor().extract_roles(claims, "kestrel-spa")
    assert roles == {"kestrel-admin", "offline_access"}


def test_extracts_client_roles_namespaced() -> None:
    """Client roles for the configured client are namespaced client_id:role."""
    claims = {
        "resource_access": {
            "kestrel-spa": {"roles": ["approver"]},
            "other-client": {"roles": ["ignored"]},
        }
    }
    roles = KeycloakRoleExtractor().extract_roles(claims, "kestrel-spa")
    assert roles == {"kestrel-spa:approver"}


def test_realm_and_client_roles_combine_without_collision() -> None:
    """A realm role and a same-named client role never collide."""
    claims = {
        "realm_access": {"roles": ["approver"]},
        "resource_access": {"kestrel-spa": {"roles": ["approver"]}},
    }
    roles = KeycloakRoleExtractor().extract_roles(claims, "kestrel-spa")
    assert roles == {"approver", "kestrel-spa:approver"}


def test_no_roles_claims_yields_empty_set() -> None:
    """A token with neither claim present yields no roles, not an error."""
    assert KeycloakRoleExtractor().extract_roles({}, "kestrel-spa") == set()


def test_get_role_extractor_keycloak() -> None:
    """The default provider resolves to the Keycloak extractor."""
    assert isinstance(get_role_extractor("keycloak"), KeycloakRoleExtractor)


def test_get_role_extractor_unknown_provider_raises() -> None:
    """An unconfigured provider name raises, not silently no-ops."""
    with pytest.raises(ValueError, match="unknown oidc_provider"):
        get_role_extractor("not-a-real-idp")
