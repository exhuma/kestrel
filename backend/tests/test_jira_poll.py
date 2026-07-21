"""Tests for the Jira poll ingestion cycle (feature 003, US1)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.ports import Task
from app.services.jira_poll import JiraPollService


class _FakeJira:
    def __init__(self, tasks, *, fields=None, fail=False) -> None:
        self._tasks = tasks
        self._fields = fields or {}
        self._fail = fail
        self.searched: list[str] = []

    async def search(self, jql, *, fields, max_results=50):
        self.searched.append(jql)
        if self._fail:
            raise RuntimeError("jira down")
        return self._tasks

    async def get_field(self, key, field):
        return self._fields.get(key)


class _FakeCodeHost:
    async def get_default_branch(self, repo):
        return "main"


class _FakeIngestion:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def maybe_start_run(self, **kw):
        self.calls.append(kw)
        return "wf-x"


class _FakeSource:
    def __init__(self) -> None:
        self.comments: list[tuple[str, str]] = []

    async def post_comment(self, ref, body):
        self.comments.append((ref, body))
        return "url"


class _FakeDismissals:
    def __init__(self, dismissed=()) -> None:
        self._d = set(dismissed)

    def all(self):
        return list(self._d)

    def is_dismissed(self, ref):
        return ref in self._d

    def clear(self, ref):
        self._d.discard(ref)


def _svc(jira, ingestion, dismissals, source=None, jql_filter="") -> JiraPollService:
    return JiraPollService(
        Settings(jira_project="RFC", jira_repo_field="cf1",
                 jira_jql_filter=jql_filter),
        jira,
        source or _FakeSource(),
        _FakeCodeHost(),
        ingestion,
        dismissals,
    )


@pytest.mark.asyncio
async def test_starts_one_run_per_qualifying_rfc() -> None:
    """Ensure each resolvable RFC starts a jira-issue run once."""
    jira = _FakeJira(
        [Task("RFC-1", "t", "b")], fields={"RFC-1": "team/svc"}
    )
    ing = _FakeIngestion()
    await _svc(jira, ing, _FakeDismissals()).run_cycle()
    assert len(ing.calls) == 1
    call = ing.calls[0]
    assert call["source"] == "jira-issue"
    assert call["task_ref"] == "RFC-1"
    assert call["code_repo"] == "team/svc"
    assert call["base_branch"] == "main"


@pytest.mark.asyncio
async def test_jql_filter_is_anded() -> None:
    """Ensure the configured JQL filter is AND-ed onto the project clause."""
    jira = _FakeJira([])
    await _svc(jira, _FakeIngestion(), _FakeDismissals(),
               jql_filter='status = "Ready"').run_cycle()
    assert jira.searched == ['project = "RFC" AND (status = "Ready")']


@pytest.mark.asyncio
async def test_unresolved_repo_starts_nothing_and_comments() -> None:
    """Ensure an RFC with no resolvable repo starts nothing and is commented."""
    jira = _FakeJira([Task("RFC-9", "t", "b")], fields={"RFC-9": None})
    ing, src = _FakeIngestion(), _FakeSource()
    await _svc(jira, ing, _FakeDismissals(), source=src).run_cycle()
    assert ing.calls == []
    assert len(src.comments) == 1 and src.comments[0][0] == "RFC-9"


@pytest.mark.asyncio
async def test_clears_dismissal_for_rfc_no_longer_qualifying() -> None:
    """Ensure a dismissed RFC that left the JQL has its dismissal cleared."""
    # RFC-5 is dismissed but not in the current qualifying set.
    jira = _FakeJira([Task("RFC-1", "t", "b")], fields={"RFC-1": "team/svc"})
    dis = _FakeDismissals(dismissed={"RFC-5", "o/r#3"})
    await _svc(jira, _FakeIngestion(), dis).run_cycle()
    assert dis.is_dismissed("RFC-5") is False   # cleared (re-trigger gesture)
    assert dis.is_dismissed("o/r#3") is True     # a GitHub dismissal is untouched


@pytest.mark.asyncio
async def test_still_qualifying_dismissal_is_kept() -> None:
    """Ensure a dismissed RFC still matching the JQL stays suppressed."""
    jira = _FakeJira([Task("RFC-5", "t", "b")], fields={"RFC-5": "team/svc"})
    dis = _FakeDismissals(dismissed={"RFC-5"})
    await _svc(jira, _FakeIngestion(), dis).run_cycle()
    assert dis.is_dismissed("RFC-5") is True


@pytest.mark.asyncio
async def test_jira_outage_is_isolated() -> None:
    """Ensure a failed poll query logs and starts nothing (no crash)."""
    ing = _FakeIngestion()
    await _svc(_FakeJira([], fail=True), ing, _FakeDismissals()).run_cycle()
    assert ing.calls == []
