"""Approved tasks as Jira work items, in the request's project or another
one, and the approved PRD as an attachment (#64)."""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.jira import JiraError, JiraTaskSource
from tests.document_helpers import doc
from tests.test_jira_client import _client, _config


class _Jira:
    """A recording Jira: every request, and an answer per path."""

    def __init__(self, found: str | None = None) -> None:
        self.calls: list[tuple[str, str, dict | bytes]] = []
        self.found = found

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/rest/api/2")
        is_json = req.headers.get("content-type", "").startswith(
            "application/json"
        )
        body = json.loads(req.content) if req.content and is_json else (
            req.content
        )
        self.calls.append((req.method, path, body))
        if path == "/search":
            hits = [{"key": self.found}] if self.found else []
            return httpx.Response(200, json={"issues": hits})
        if path == "/issue":
            return httpx.Response(201, json={"key": "DEV-7"})
        if path.endswith("/attachments"):
            assert req.headers["x-atlassian-token"] == "no-check"
            return httpx.Response(200, json=[{"content": "https://f/PRD.md"}])
        if path.endswith("/remotelink") and req.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json={})

    def posted(self, path: str) -> list[dict]:
        return [body for method, p, body in self.calls
                if method == "POST" and p == path]


def _source(jira: _Jira, **config: str) -> JiraTaskSource:
    return JiraTaskSource(
        _client(jira, auth="basic", email="e", token="t"),
        config=_config(repo_field="", **config),
    )


@pytest.mark.asyncio
async def test_without_a_target_project_a_task_is_a_sub_task() -> None:
    """Ensure the default layout keeps the work under the request."""
    jira = _Jira()

    ref = await _source(jira).create_subtask(
        "RFC-1", "Add the table", doc("body"), key="kestrel-wf-1-t1"
    )

    assert ref == "DEV-7"
    fields = jira.posted("/issue")[0]["fields"]
    assert fields["issuetype"] == {"name": "Sub-task"}
    assert fields["parent"] == {"key": "RFC-1"}
    assert fields["project"] == {"key": "RFC"}
    assert fields["labels"] == ["kestrel-wf-1-t1"]
    assert jira.posted("/issueLink") == []


@pytest.mark.asyncio
async def test_with_a_target_project_a_task_is_a_linked_issue() -> None:
    """Ensure a cross-project item has the configured type and link, and
    no parent, which Jira would refuse across projects."""
    jira = _Jira()
    source = _source(
        jira, work_items_project="DEV", work_items_link_type="Implements",
    )

    await source.create_subtask("RFC-1", "Add the table", doc("body"))

    fields = jira.posted("/issue")[0]["fields"]
    assert fields["project"] == {"key": "DEV"}
    assert fields["issuetype"] == {"name": "Task"}
    assert "parent" not in fields
    (link,) = jira.posted("/issueLink")
    assert link["type"] == {"name": "Implements"}
    assert {link["inwardIssue"]["key"], link["outwardIssue"]["key"]} == {
        "DEV-7", "RFC-1",
    }


@pytest.mark.asyncio
async def test_an_item_created_before_a_crash_is_found_again() -> None:
    """Ensure a retry finds the item by its label instead of doubling it."""
    jira = _Jira(found="DEV-3")

    ref = await _source(jira).create_subtask(
        "RFC-1", "Add the table", doc("body"), key="kestrel-wf-1-t1"
    )

    assert ref == "DEV-3"
    assert jira.posted("/issue") == []
    assert 'labels = "kestrel-wf-1-t1"' in jira.posted("/search")[0]["jql"]


@pytest.mark.asyncio
async def test_a_prerequisite_is_a_blocks_link() -> None:
    """Ensure the blocking item reads "blocks" towards the blocked one."""
    jira = _Jira()

    await _source(jira).link_subtasks("DEV-1", "DEV-2")

    (link,) = jira.posted("/issueLink")
    assert link["type"] == {"name": "Blocks"}
    assert link["inwardIssue"] == {"key": "DEV-1"}
    assert link["outwardIssue"] == {"key": "DEV-2"}


@pytest.mark.asyncio
async def test_the_prd_is_attached_as_a_markdown_file() -> None:
    """Ensure the document is uploaded as a file, with Jira's XSRF opt-out
    header, and its rendered text is the file's content."""
    jira = _Jira()

    url = await _source(jira).attach_document(
        "RFC-1", "PRD.md", doc("The requirements")
    )

    assert url == "https://f/PRD.md"
    (_method, path, body) = jira.calls[0]
    assert path == "/issue/RFC-1/attachments"
    assert b'filename="PRD.md"' in body
    assert b"The requirements" in body


@pytest.mark.asyncio
async def test_the_health_check_names_a_setting_jira_does_not_know() -> None:
    """Ensure a wrong type or link name shows before CAB-2, not at it."""

    def jira(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/issueLinkType"):
            return httpx.Response(
                200, json={"issueLinkTypes": [{"name": "Blocks"}]}
            )
        if req.url.path.endswith("/project/DEV"):
            return httpx.Response(200, json={"issueTypes": [{"name": "Bug"}]})
        return httpx.Response(200, json={})

    source = JiraTaskSource(
        _client(jira, auth="basic", email="e", token="t"),
        config=_config(work_items_project="DEV"),
    )

    with pytest.raises(JiraError) as caught:
        await source.check_health()

    assert "'Relates'" in str(caught.value)
    assert "'Task'" in str(caught.value)
