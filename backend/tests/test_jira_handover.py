"""Who has a Jira work item, and whether it is done (#99): the assignee
against the account behind the token, the hand-over query, and the
status category."""
from __future__ import annotations

import json

import httpx
import pytest

from app.ports import WorkItemState
from app.services.jira import JiraTaskSource
from tests.test_jira_client import _client, _config

_KESTREL = {"accountId": "acc-kestrel", "displayName": "kestrel"}
_PERSON = {"accountId": "acc-ann", "displayName": "Ann"}


def _issue(key: str, assignee: dict | None, category: str) -> dict:
    return {
        "key": key,
        "fields": {
            "assignee": assignee,
            "status": {"statusCategory": {"key": category}},
        },
    }


class _Jira:
    """A Jira that answers ``/myself`` and two searches: every item, and
    the items matching the hand-over query."""

    def __init__(self, issues: list[dict], matching: list[str]) -> None:
        self.issues = issues
        self.matching = matching
        self.searches: list[str] = []
        self.myself_calls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/rest/api/2")
        if path == "/myself":
            self.myself_calls += 1
            return httpx.Response(200, json=_KESTREL)
        assert path == "/search"
        jql = json.loads(req.content)["jql"]
        self.searches.append(jql)
        if " AND (" in jql:
            hits = [{"key": key} for key in self.matching]
            return httpx.Response(200, json={"issues": hits, "total": 1})
        return httpx.Response(
            200, json={"issues": self.issues, "total": len(self.issues)}
        )


def _source(jira: _Jira, **config: str) -> JiraTaskSource:
    return JiraTaskSource(
        _client(jira, auth="basic", email="e", token="t"),
        config=_config(**config),
    )


@pytest.mark.asyncio
async def test_an_item_assigned_to_kestrel_is_handed_over() -> None:
    """Ensure the assignee is compared with the token's own account, in
    one search for every item."""
    jira = _Jira([
        _issue("DEV-1", _KESTREL, "indeterminate"),
        _issue("DEV-2", _PERSON, "new"),
        _issue("DEV-3", None, "new"),
    ], [])

    states = await _source(jira).work_item_states(["DEV-1", "DEV-2", "DEV-3"])

    assert states == {
        "DEV-1": WorkItemState(handed_to_kestrel=True, done=False),
        "DEV-2": WorkItemState(handed_to_kestrel=False, done=False),
        "DEV-3": WorkItemState(handed_to_kestrel=False, done=False),
    }
    assert jira.searches == ['key in ("DEV-1", "DEV-2", "DEV-3")']


@pytest.mark.asyncio
async def test_an_item_matching_the_hand_over_query_is_handed_over() -> None:
    """Ensure ``work_items_jql`` hands over an item whoever has it, with
    one more search limited to the same keys."""
    jira = _Jira([
        _issue("DEV-1", _PERSON, "new"), _issue("DEV-2", _PERSON, "new"),
    ], ["DEV-2"])

    states = await _source(
        jira, work_items_jql="labels = kestrel"
    ).work_item_states(["DEV-1", "DEV-2"])

    assert states["DEV-1"].handed_to_kestrel is False
    assert states["DEV-2"].handed_to_kestrel is True
    assert jira.searches[1] == (
        'key in ("DEV-1", "DEV-2") AND (labels = kestrel)'
    )


@pytest.mark.asyncio
async def test_an_item_in_a_done_status_is_done() -> None:
    """Ensure the status category, not a status name, says done."""
    jira = _Jira([_issue("DEV-1", _PERSON, "done")], [])

    states = await _source(jira).work_item_states(["DEV-1"])

    assert states["DEV-1"] == WorkItemState(
        handed_to_kestrel=False, done=True
    )


@pytest.mark.asyncio
async def test_the_kestrel_account_is_read_once() -> None:
    """Ensure ``/myself`` is asked once, not on every poll."""
    jira = _Jira([_issue("DEV-1", _KESTREL, "new")], [])
    source = _source(jira)

    await source.work_item_states(["DEV-1"])
    await source.work_item_states(["DEV-1"])

    assert jira.myself_calls == 1


@pytest.mark.asyncio
async def test_a_ref_that_is_not_an_issue_key_is_never_queried() -> None:
    """Ensure nothing but an issue key reaches the query."""
    jira = _Jira([], [])

    states = await _source(jira).work_item_states(['X") OR (1=1'])

    assert states == {}
    assert jira.searches == []


def test_jira_supports_hand_over() -> None:
    """Ensure Jira approved tasks wait to be handed over."""
    assert _source(_Jira([], [])).supports_handover() is True
