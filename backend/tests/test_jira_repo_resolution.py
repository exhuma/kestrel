"""Tests for Jira repo resolution from the configurable field (feature 003)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.services.jira_poll import JiraPollService


class _FakeJira:
    def __init__(self, field_value) -> None:
        self._field_value = field_value

    async def get_field(self, key, field):
        return self._field_value


class _FakeCodeHost:
    def __init__(self, *, reachable=True, default="main") -> None:
        self._reachable = reachable
        self._default = default

    async def get_default_branch(self, repo):
        if not self._reachable:
            raise RuntimeError("unreachable")
        return self._default


def _svc(field_value, *, reachable=True, default="main") -> JiraPollService:
    return JiraPollService(
        Settings(jira_project="RFC", jira_repo_field="customfield_1"),
        _FakeJira(field_value),
        source=None,
        code_host=_FakeCodeHost(reachable=reachable, default=default),
        ingestion=None,
        dismissals=None,
    )


@pytest.mark.asyncio
async def test_resolves_repo_and_default_branch() -> None:
    """Ensure a bare owner/name resolves with the host's default branch."""
    assert await _svc("team/svc")._resolve_repo("RFC-1") == ("team/svc", "main")


@pytest.mark.asyncio
async def test_resolves_repo_with_explicit_base_branch() -> None:
    """Ensure owner/name@branch overrides the default branch."""
    assert await _svc("team/svc@develop")._resolve_repo("RFC-1") == (
        "team/svc", "develop"
    )


@pytest.mark.asyncio
async def test_empty_field_is_unresolved() -> None:
    """Ensure an empty/missing field yields None (no run)."""
    assert await _svc(None)._resolve_repo("RFC-1") is None
    assert await _svc("   ")._resolve_repo("RFC-1") is None


@pytest.mark.asyncio
async def test_unreachable_repo_is_unresolved() -> None:
    """Ensure a repo the code host cannot reach yields None."""
    svc = _svc("team/svc", reachable=False)
    assert await svc._resolve_repo("RFC-1") is None
