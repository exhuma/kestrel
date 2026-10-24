"""Bounded opencode tool use (feature 036): the allowlist, the loop guard,
and a looping turn stopped end to end."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.backends.base import TurnRequest, TurnStopped
from app.backends.opencode import OpenCodeBackend
from app.backends.opencode_tools import ToolLoopGuard, ToolPolicy, tools_map
from app.config import BackendConfig, Settings
from app.storage.registry import SessionRegistry

_POLICY = ToolPolicy(allowed=None, max_calls=4, max_repeats=3)


def _part(call_id: str, tool: str = "gitlab_list_project_issues",
          arguments: dict | None = None, status: str = "running") -> dict:
    return {
        "type": "tool", "callID": call_id, "tool": tool,
        "sessionID": "oc-1",
        "state": {"status": status, "input": arguments or {"project": "x"}},
    }


# --- config ------------------------------------------------------------------

def test_an_allowlist_is_rejected_where_it_would_be_ignored() -> None:
    """Ensure a claude_cli/openai_compat allowlist fails loudly (FR-001)."""
    with pytest.raises(ValidationError, match="only by opencode"):
        BackendConfig(id="c", type="claude_cli", allowed_tools=["read"])


def test_tool_limits_default_sensibly() -> None:
    cfg = BackendConfig(id="oc", type="opencode", allowed_tools=["read"])
    policy = ToolPolicy.of(cfg)

    assert policy == ToolPolicy(allowed=("read",), max_calls=150, max_repeats=5)


# --- the tools map -----------------------------------------------------------

def test_no_allowlist_leaves_a_writing_turn_alone() -> None:
    assert tools_map(_POLICY, read_only=False) is None


def test_an_allowlist_denies_everything_else_first() -> None:
    """Ensure the catch-all deny precedes the allows: opencode's last
    matching rule wins."""
    policy = ToolPolicy(("read", "grep"), 150, 5)

    assert list(tools_map(policy, read_only=False).items()) == [
        ("*", False), ("read", True), ("grep", True),
    ]


def test_a_read_only_turn_still_cannot_write_when_writing_is_listed() -> None:
    tools = tools_map(ToolPolicy(("read", "edit"), 150, 5), read_only=True)

    assert tools["edit"] is False
    assert list(tools)[-1] in {"edit", "patch", "question", "task", "write"}
    assert list(tools).index("edit") > list(tools).index("read")


# --- the guard ---------------------------------------------------------------

def test_the_same_call_repeated_trips_the_guard() -> None:
    guard = ToolLoopGuard(_POLICY, None)

    tripped = [guard.observe(_part(f"c{i}")) for i in range(3)]

    assert tripped == [False, False, True]
    assert guard.tripped == (
        "it called gitlab_list_project_issues 3 times with the same input"
    )


def test_one_call_is_counted_once_across_its_updates() -> None:
    """Ensure running → completed updates of one call are one call."""
    guard = ToolLoopGuard(_POLICY, None)
    for status in ("pending", "running", "completed"):
        guard.observe(_part("c1", status=status))
    guard.observe(_part("c2"))

    assert guard.tripped is None


def test_varied_calls_trip_only_the_budget() -> None:
    guard = ToolLoopGuard(_POLICY, None)
    for i in range(5):
        guard.observe(_part(f"c{i}", arguments={"page": i}))

    assert guard.tripped == "it made more than 4 tool calls"


def test_each_new_call_is_told_and_a_failing_observer_is_harmless() -> None:
    told: list[str] = []

    def on_tool(tool: str) -> None:
        told.append(tool)
        raise RuntimeError("display broke")

    guard = ToolLoopGuard(_POLICY, on_tool)
    guard.observe(_part("c1", tool="read"))
    guard.observe(_part("c1", tool="read", status="completed"))
    guard.observe({"type": "text", "text": "hi"})

    assert told == ["read"]


# --- a looping turn, end to end ---------------------------------------------

def await_value(response: httpx.Response):
    """A route answering every request with *response*."""
    async def reply(_request: httpx.Request) -> httpx.Response:
        return response
    return reply


def _looping_server(seen: list[httpx.Request]):
    """An opencode server whose model calls one tool over and over; the
    turn's POST only returns once the session is aborted."""
    aborted = asyncio.Event()
    frames = "".join(
        "data: " + json.dumps({
            "type": "message.part.updated",
            "properties": {"sessionID": "oc-1", "part": _part(f"c{i}")},
        }) + "\n\n"
        for i in range(10)
    ).encode()

    async def post_message(_request: httpx.Request) -> httpx.Response:
        await asyncio.wait_for(aborted.wait(), timeout=5)
        return httpx.Response(200, json={
            "info": {"id": "a1", "error": {"name": "MessageAbortedError"}},
            "parts": [],
        })

    async def abort(_request: httpx.Request) -> httpx.Response:
        aborted.set()
        return httpx.Response(200, json=True)

    routes = {
        ("POST", "/session"): await_value(
            httpx.Response(200, json={"id": "oc-1"})
        ),
        ("GET", "/event"): await_value(httpx.Response(200, content=frames)),
        ("POST", "/session/oc-1/abort"): abort,
        ("POST", "/session/oc-1/message"): post_message,
        ("GET", "/session/oc-1/message"): await_value(
            httpx.Response(200, json=[])
        ),
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        route = routes.get((request.method, request.url.path))
        return await route(request) if route else httpx.Response(404)

    return handler


@pytest.mark.asyncio
async def test_a_looping_turn_is_aborted_and_says_why() -> None:
    """Ensure a model repeating one call is stopped within the limit, the
    session aborted, and the turn failed with kestrel's own reason."""
    seen: list[httpx.Request] = []
    cfg = BackendConfig(
        id="oc", type="opencode", base_url="http://oc.local:4096",
        allowed_tools=["read"], max_repeated_tool_calls=3,
    )
    transport = httpx.MockTransport(_looping_server(seen))
    client = httpx.AsyncClient(transport=transport)
    backend = OpenCodeBackend(
        Settings(_env_file=None, workspace_root="/tmp/ws"),
        SessionRegistry(), cfg, client=client,
    )
    told: list[str] = []

    with pytest.raises(TurnStopped) as stopped:
        await backend.run_turn(TurnRequest(
            prompt="write the PRD", cwd="", permission_mode="plan",
            on_tool=told.append,
        ))

    assert stopped.value.reason == (
        "it called gitlab_list_project_issues 3 times with the same input"
    )
    # Calls already under way when the abort lands are still reported.
    assert set(told) == {"gitlab_list_project_issues"}
    assert len(told) >= cfg.max_repeated_tool_calls
    (post,) = [
        r for r in seen
        if r.url.path == "/session/oc-1/message" and r.method == "POST"
    ]
    assert json.loads(post.content)["tools"]["*"] is False
