"""Tests for Jira repo resolution: field, web link, and URL parsing (004)."""
from __future__ import annotations

import pytest

from app.config_models import TaskSourceConfig
from app.services.jira_poll import JiraPollService, _repo_from_url


class _FakeJira:
    def __init__(self, field_value, *, links=None) -> None:
        self._field_value = field_value
        self._links = links or []

    async def get_field(self, key, field):
        return self._field_value

    async def get_remote_links(self, key):
        return self._links


class _FakeCodeHost:
    def __init__(self, *, reachable=True, default="main") -> None:
        self._reachable = reachable
        self._default = default

    async def get_default_branch(self, repo):
        if not self._reachable:
            raise RuntimeError("unreachable")
        return self._default


def _svc(
    field_value, *, reachable=True, default="main", links=None,
    repo_field="customfield_1",
) -> JiraPollService:
    cfg = TaskSourceConfig(
        type="jira", base_url="https://jira.example",
        jql='project = "RFC"', key="RFC", repo_field=repo_field,
    )
    return JiraPollService(
        cfg,
        _FakeJira(field_value, links=links),
        None,
        _FakeCodeHost(reachable=reachable, default=default),
        None,
        None,
    )


def _link(title, url):
    return {"object": {"title": title, "url": url}}


@pytest.mark.parametrize(
    ("url", "code_host", "expected"),
    [
        ("https://github.com/acme/gateway", "github", "acme/gateway"),
        ("https://github.com/acme/gateway.git", "github", "acme/gateway"),
        ("https://github.com/acme/gateway/", "github", "acme/gateway"),
        # GitHub deep link is trimmed to owner/name.
        ("https://github.com/acme/gateway/issues/5", "github", "acme/gateway"),
        # GitLab keeps subgroups, truncates the /-/ deep-link tail.
        ("https://gitlab.host/group/sub/proj", "gitlab", "group/sub/proj"),
        ("https://gitlab.host/group/proj/-/issues/3", "gitlab", "group/proj"),
        # Non-http(s) schemes and too-short paths are unresolved.
        ("git@github.com:acme/gateway.git", "github", None),
        ("ssh://git@gitlab.host/group/proj.git", "gitlab", None),
        ("https://example.com/", "github", None),
        ("not a url", "github", None),
    ],
)
def test_repo_from_url(url, code_host, expected) -> None:
    """Ensure owner/name is parsed from http(s) URLs per host, else None."""
    assert _repo_from_url(url, code_host) == expected


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


@pytest.mark.asyncio
async def test_resolves_from_web_link_when_field_absent() -> None:
    """Ensure a titled web link resolves the repo when no field is set."""
    svc = _svc(
        None, repo_field="",
        links=[_link("Repository", "https://github.com/team/svc")],
    )
    assert await svc._resolve_repo("RFC-1") == ("team/svc", "main")


@pytest.mark.asyncio
async def test_web_link_title_match_is_case_insensitive() -> None:
    """Ensure the configured link text matches regardless of case."""
    svc = _svc(
        None, repo_field="",
        links=[_link("repository", "https://github.com/team/svc")],
    )
    assert await svc._resolve_repo("RFC-1") == ("team/svc", "main")


@pytest.mark.asyncio
async def test_field_wins_over_web_link() -> None:
    """Ensure a present field is used before the web-link fallback."""
    svc = _svc(
        "team/from-field",
        links=[_link("Repository", "https://github.com/team/from-link")],
    )
    assert await svc._resolve_repo("RFC-1") == ("team/from-field", "main")


@pytest.mark.asyncio
async def test_non_matching_link_is_ignored() -> None:
    """Ensure a link whose title differs is not used (stays unresolved)."""
    svc = _svc(
        None, repo_field="",
        links=[_link("Docs", "https://github.com/team/svc")],
    )
    assert await svc._resolve_repo("RFC-1") is None


@pytest.mark.asyncio
async def test_neither_field_nor_link_is_unresolved() -> None:
    """Ensure an RFC with no field and no matching link resolves to None."""
    assert await _svc(None, repo_field="", links=[])._resolve_repo(
        "RFC-1"
    ) is None
