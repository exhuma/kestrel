"""Tests for the permission vocabulary and role-mapping resolution."""
from __future__ import annotations

import pytest

from app.auth.permissions import PERMISSIONS, resolve_permissions
from app.config import Settings
from app.config_models import RoleMapping


def test_resolve_permissions_unions_matching_mappings() -> None:
    """A role matching two mappings grants the union of both."""
    mappings = [
        RoleMapping(role="kestrel-approver", permissions=["workflows:approve"]),
        RoleMapping(role="kestrel-approver", permissions=["workflows:reject"]),
        RoleMapping(role="kestrel-admin", permissions=["workflows:cleanup"]),
    ]
    granted = resolve_permissions({"kestrel-approver"}, mappings)
    assert granted == frozenset({"workflows:approve", "workflows:reject"})


def test_resolve_permissions_no_matching_role_is_empty() -> None:
    """An authenticated user with no matching role gets zero permissions,
    not an error (view-only is a valid state)."""
    mappings = [
        RoleMapping(role="kestrel-admin", permissions=["workflows:cleanup"])
    ]
    assert resolve_permissions({"kestrel-viewer"}, mappings) == frozenset()


def test_resolve_permissions_empty_mappings_is_empty() -> None:
    """No configured mappings at all resolves to no permissions."""
    assert resolve_permissions({"anything"}, []) == frozenset()


def test_permissions_vocabulary_matches_gated_endpoints() -> None:
    """Sanity-check the fixed vocabulary size/shape (data-model.md)."""
    assert frozenset(
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
    ) == PERMISSIONS


def test_settings_rejects_unknown_permission_string() -> None:
    """An unknown permission in role_mappings fails fast at startup."""
    with pytest.raises(ValueError, match="workflows:not-a-real-permission"):
        Settings(
            role_mappings=[
                RoleMapping(
                    role="kestrel-admin",
                    permissions=["workflows:not-a-real-permission"],
                )
            ]
        )


def test_settings_accepts_valid_permission_strings() -> None:
    """Every real permission string is accepted without error."""
    settings = Settings(
        role_mappings=[
            RoleMapping(role="kestrel-admin", permissions=list(PERMISSIONS))
        ]
    )
    assert set(settings.role_mappings[0].permissions) == PERMISSIONS
