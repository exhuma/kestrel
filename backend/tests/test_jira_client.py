"""Tests for the Jira REST client + TaskSource adapter (feature 003)."""
from __future__ import annotations

import json
import ssl

import httpx
import pytest

from app.config_models import TaskSourceConfig
from app.ports import LifecycleEvent, Task
from app.services.jira import JiraClient, JiraError, JiraTaskSource


def _client(handler, **kw) -> JiraClient:
    client = JiraClient("https://jira.example", **kw)
    client._http = httpx.AsyncClient(
        base_url="https://jira.example/rest/api/2",
        transport=httpx.MockTransport(handler),
        auth=client._http.auth,
    )
    return client


def _verify_mode(client: JiraClient) -> ssl.VerifyMode:
    """The TLS verify mode of the client's underlying httpx transport."""
    return client._http._transport._pool._ssl_context.verify_mode


def test_verify_flag_toggles_tls_verification() -> None:
    """Ensure verify=False builds an httpx client that skips cert checks."""
    secure = JiraClient("https://jira.example", token="t")
    insecure = JiraClient("https://jira.example", token="t", verify=False)
    assert _verify_mode(secure) == ssl.CERT_REQUIRED
    assert _verify_mode(insecure) == ssl.CERT_NONE


@pytest.mark.asyncio
async def test_search_parses_issues_and_paginates() -> None:
    """search() POSTs to /search/jql and follows nextPageToken to the end."""
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append({"path": req.url.path, "method": req.method, "body": body})
        if body.get("nextPageToken") is None:
            return httpx.Response(200, json={
                "issues": [
                    {"key": "RFC-1",
                     "fields": {"summary": "One", "description": "d1"}},
                ],
                "nextPageToken": "tok2",
                "isLast": False,
            })
        return httpx.Response(200, json={
            "issues": [
                {"key": "RFC-2",
                 "fields": {"summary": "Two", "description": None}},
            ],
            "isLast": True,
        })

    page_size = 25
    tasks = await _client(handler, auth="basic", email="e", token="t").search(
        'project = "RFC"', fields=["summary", "description"],
        max_results=page_size,
    )
    assert tasks == [
        Task(ref="RFC-1", title="One", body="d1"),
        Task(ref="RFC-2", title="Two", body=""),
    ]
    assert [s["method"] for s in seen] == ["POST", "POST"]
    assert seen[0]["path"].endswith("/search/jql")
    assert seen[0]["body"]["maxResults"] == page_size
    assert seen[0]["body"]["fields"] == ["summary", "description"]
    assert seen[1]["body"]["nextPageToken"] == "tok2"


@pytest.mark.asyncio
async def test_get_field_returns_value_or_none() -> None:
    """Ensure get_field reads a scalar field, or None when empty."""
    def handler(req: httpx.Request) -> httpx.Response:
        if "customfield_1" in str(req.url):
            return httpx.Response(200, json={
                "key": "RFC-1", "fields": {"customfield_1": "team/svc@dev"}
            })
        return httpx.Response(200, json={"key": "RFC-1", "fields": {}})

    client = _client(handler, auth="basic", email="e", token="t")
    assert await client.get_field("RFC-1", "customfield_1") == "team/svc@dev"
    assert await client.get_field("RFC-1", "missing") is None


@pytest.mark.asyncio
async def test_add_comment_and_attachment() -> None:
    """Ensure comment/attachment hit the right paths and headers."""
    seen = {}
    bodies = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen[req.url.path] = req.headers.get("x-atlassian-token")
        bodies[req.url.path] = req.content
        if req.url.path.endswith("/comment"):
            return httpx.Response(201, json={"self": "https://jira/c/1"})
        return httpx.Response(200, json=[{"id": "1"}])

    client = _client(handler, auth="basic", email="e", token="t")
    assert await client.add_comment("RFC-1", "hi") == "https://jira/c/1"
    await client.add_attachment(
        "RFC-1", "shot.png", b"\x89PNGbytes", "image/png"
    )
    assert seen["/rest/api/2/issue/RFC-1/comment"] is None
    # Attachment carries the XSRF-bypass header.
    assert seen["/rest/api/2/issue/RFC-1/attachments"] == "no-check"
    # The raw bytes and declared mimetype ride in the multipart body.
    attach_body = bodies["/rest/api/2/issue/RFC-1/attachments"]
    assert b"\x89PNGbytes" in attach_body
    assert b"image/png" in attach_body


@pytest.mark.asyncio
async def test_bearer_auth_sets_header() -> None:
    """Ensure bearer auth sends an Authorization: Bearer header."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"issues": []})

    await _client(handler, auth="bearer", token="pat-123").search(
        "project = RFC", fields=["summary"]
    )
    assert seen["auth"] == "Bearer pat-123"


@pytest.mark.asyncio
async def test_error_does_not_leak_token() -> None:
    """Ensure a raised JiraError never contains the token."""
    with pytest.raises(JiraError) as exc:
        await _client(
            lambda r: httpx.Response(500, text="boom"),
            auth="bearer", token="pat-supersecret",
        ).get_issue("RFC-1")
    assert "pat-supersecret" not in str(exc.value)


@pytest.mark.asyncio
async def test_task_source_publishes_prd_as_attachment() -> None:
    """Ensure JiraTaskSource.publish_refined attaches PRD.md."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        return httpx.Response(200, json=[{"id": "1"}])

    src = JiraTaskSource(_client(handler, auth="basic", email="e", token="t"))
    await src.publish_refined("RFC-1", "the PRD")
    assert seen["path"].endswith("/issue/RFC-1/attachments")
    assert src.deep_link_ref("RFC-1") == "https://jira.example/browse/RFC-1"


def _config(**overrides) -> TaskSourceConfig:
    base = dict(
        type="jira", base_url="https://jira.example", jql="x", key="RFC"
    )
    base.update(overrides)
    return TaskSourceConfig(**base)


@pytest.mark.asyncio
async def test_transition_applies_configured_transition_id() -> None:
    """Ensure a configured transition id is POSTed for the matching kind."""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.read())
        return httpx.Response(200, json={})

    cfg = _config(transition_done="31")
    src = JiraTaskSource(
        _client(handler, auth="basic", email="e", token="t"), config=cfg
    )
    ok = await src.transition("RFC-1", LifecycleEvent(kind="done"))
    assert ok is True
    assert seen["path"].endswith("/issue/RFC-1/transitions")
    assert seen["body"] == {"transition": {"id": "31"}}


@pytest.mark.asyncio
async def test_transition_is_noop_when_unconfigured() -> None:
    """Ensure an unset transition id is a no-op, not an error."""

    def handler(_req: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not call Jira when unconfigured")

    src = JiraTaskSource(
        _client(handler, auth="basic", email="e", token="t"), config=_config()
    )
    ok = await src.transition("RFC-1", LifecycleEvent(kind="done"))
    assert ok is False


@pytest.mark.asyncio
async def test_transition_failure_returns_false_without_raising() -> None:
    """Ensure a failed transition call returns False, never raises."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errorMessages": ["bad"]})

    cfg = _config(transition_done="31")
    src = JiraTaskSource(
        _client(handler, auth="basic", email="e", token="t"), config=cfg
    )
    ok = await src.transition("RFC-1", LifecycleEvent(kind="done"))
    assert ok is False


@pytest.mark.asyncio
async def test_transition_writes_configured_time_field_independently() -> None:
    """Ensure the time field is written even if no transition is configured."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, json.loads(req.read())))
        return httpx.Response(200, json={})

    cfg = _config(time_spent_field="timespent")
    src = JiraTaskSource(
        _client(handler, auth="basic", email="e", token="t"), config=cfg
    )
    ok = await src.transition(
        "RFC-1", LifecycleEvent(kind="done", active_seconds=125.6)
    )
    assert ok is False  # no transition_done configured
    method, path, body = calls[0]
    assert len(calls) == 1
    assert method == "PUT"
    assert path.endswith("/issue/RFC-1")
    assert body == {"fields": {"timespent": 126}}


def test_supports_time_spent_reflects_configured_field() -> None:
    """Ensure supports_time_spent() matches whether time_spent_field is set."""
    client = _client(lambda r: httpx.Response(200), auth="basic")
    unset = JiraTaskSource(client, config=_config())
    assert unset.supports_time_spent() is False
    cfg = _config(time_spent_field="timespent")
    assert JiraTaskSource(client, config=cfg).supports_time_spent() is True
    assert JiraTaskSource(client, config=None).supports_time_spent() is False
