"""Kestrel's internal reasoning: required config, the OpenAI-compatible
client, and which turns run on it rather than on an agent backend."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.backends.base import (
    BackendTurnError,
    BackendUnavailable,
    TurnRequest,
)
from app.backends.limiter import BackendLimiter
from app.config import Settings
from app.config_reasoning import ReasoningConfig, ReasoningEndpoint
from app.models_board import WorkCard
from app.reasoning.client import (
    ReasoningBlocked,
    ReasoningClient,
    ReasoningTarget,
)
from app.reasoning.policy import ReasoningPolicy
from app.services.board.dispatch import ClassificationError, classify_input
from app.services.board.dispatch_ready import dispatch_ready_work
from app.services.board.specialists import SpecialistRoster
from tests.test_board_scheduling import (
    _dispatch_services,
    _FakeBackend,
    _specialist,
)

_ENDPOINT = ReasoningEndpoint(
    base_url="https://llm.test/v1", model="m-1", api_key_env="TEST_RSN_KEY"
)


def _answer(content: str, finish: str = "stop") -> dict:
    return {
        "choices": [{
            "finish_reason": finish,
            "message": {"role": "assistant", "content": content},
        }],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }


def _client(*responses: httpx.Response | Exception) -> tuple[
    ReasoningClient, list[httpx.Request]
]:
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    target = ReasoningTarget("liaison", _ENDPOINT)
    return ReasoningClient(target, BackendLimiter(1), http), seen


def _request(**extra: object) -> TurnRequest:
    return TurnRequest(prompt="hello", cwd="", permission_mode="read_only",
                       **extra)


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_RSN_KEY", "secret")


@pytest.mark.asyncio
async def test_a_turn_is_one_chat_completion() -> None:
    """Ensure the prompt goes to the configured model with the key, and
    the answer comes back with a session id."""
    client, seen = _client(httpx.Response(200, json=_answer("fine")))
    ids: list[str] = []

    result = await client.run_turn(_request(on_session_id=ids.append))

    assert result.final_text == "fine"
    assert ids == [result.session_id]
    assert result.session_id.startswith("rsn-")
    request = seen[0]
    assert str(request.url) == "https://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret"
    body = json.loads(request.content)
    assert body["model"] == "m-1"
    assert body["messages"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_a_rate_limit_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a 429 is waited out rather than failing the turn."""
    monkeypatch.setattr(
        "app.reasoning.client._RATE_LIMIT_BACKOFF_SECONDS", 0.01
    )
    client, seen = _client(
        httpx.Response(429, headers={"retry-after": "0.01"}),
        httpx.Response(200, json=_answer("after")),
    )

    result = await client.run_turn(_request())

    assert result.final_text == "after"
    assert [r.url.path for r in seen] == ["/v1/chat/completions"] * 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    httpx.Response(200, json=_answer("", finish="content_filter")),
    httpx.Response(400, json={"error": {"code": "content_filter"}}),
])
async def test_a_content_filter_block_is_its_own_failure(
    reply: httpx.Response,
) -> None:
    """Ensure a filter block is told apart from a failure."""
    client, _seen = _client(reply)

    with pytest.raises(ReasoningBlocked):
        await client.run_turn(_request())


@pytest.mark.asyncio
@pytest.mark.parametrize(("reply", "error"), [
    (httpx.Response(500, json={}), BackendTurnError),
    (httpx.Response(200, json=_answer("   ")), BackendTurnError),
    (httpx.Response(200, json={"choices": []}), BackendTurnError),
    (httpx.ReadTimeout("slow"), TimeoutError),
    (httpx.ConnectError("down"), BackendUnavailable),
])
async def test_every_other_failure_is_named(
    reply: httpx.Response | Exception, error: type[Exception],
) -> None:
    """Ensure no failure passes as an answer, and each is classified."""
    client, _seen = _client(reply)

    with pytest.raises(error):
        await client.run_turn(_request())


def test_a_role_override_changes_only_what_it_sets() -> None:
    """Ensure a role table inherits every field it leaves out."""
    config = ReasoningConfig(
        base_url="https://a/v1", model="small",
        roles={"input-security": {"model": "careful"}},
    )

    screening = config.for_role("input-security")

    assert (screening.base_url, screening.model) == ("https://a/v1", "careful")
    assert config.for_role("liaison").model == "small"


def test_one_endpoint_shares_one_concurrency_limit() -> None:
    """Ensure roles on the same endpoint do not each get their own slots,
    and the health view lists each endpoint once."""
    policy = ReasoningPolicy(ReasoningConfig(
        base_url="https://a/v1", model="m",
        roles={
            "liaison": {"model": "other"},
            "input-security": {"base_url": "https://b/v1"},
        },
    ))

    assert policy.for_role("pm")._limiter is policy.for_role("liaison")._limiter
    assert [label for label, _ in policy.health_checks()] == [
        "reasoning", "reasoning:input-security",
    ]


def test_an_unknown_role_table_is_refused() -> None:
    """Ensure a typo in a role name fails instead of being ignored."""
    policy = ReasoningPolicy(ReasoningConfig(
        base_url="https://a/v1", model="m", roles={"liason": {}},
    ))

    with pytest.raises(ValueError, match="liason"):
        policy.require_known_roles({"liaison", "pm"})


@pytest.mark.parametrize(("reasoning", "message"), [
    (None, "is not configured"),
    ({"base_url": "", "model": "m"}, "base_url is empty"),
    ({"base_url": "https://a/v1", "model": ""}, "model is empty"),
    ({"base_url": "https://a/v1", "model": "m",
      "api_key_env": "UNSET_RSN_KEY"}, "UNSET_RSN_KEY is not set"),
])
def test_kestrel_does_not_start_without_working_reasoning(
    monkeypatch: pytest.MonkeyPatch, reasoning: dict | None, message: str,
) -> None:
    """Ensure every missing piece stops startup with a clear message."""
    monkeypatch.delenv("UNSET_RSN_KEY", raising=False)
    monkeypatch.delenv("KESTREL_REASONING", raising=False)

    with pytest.raises(ValueError, match=message):
        Settings(_env_file=None, reasoning=reasoning)


@pytest.mark.asyncio
async def test_screening_reports_a_filter_block() -> None:
    """Ensure a filtered screening is held with that reason."""

    class _Blocked:
        async def run_turn(self, _req: TurnRequest):
            raise ReasoningBlocked("filtered")

    with pytest.raises(ClassificationError) as caught:
        await classify_input(_Blocked(), "envelope", timeout_seconds=1)

    assert caught.value.category == "content_filter"


class _Reasoning:
    def __init__(self, backend: _FakeBackend) -> None:
        self.backend = backend

    def backend_for(self, _specialist: object) -> _FakeBackend:
        return self.backend


@pytest.mark.asyncio
@pytest.mark.parametrize(("permission", "reasons"), [
    ("none", True), ("read_only", False),
])
async def test_only_a_card_without_a_workspace_runs_on_reasoning(
    tmp_path: Path, permission: str, reasons: bool,
) -> None:
    """Ensure the one rule: no checkout means kestrel reasons itself; a
    card with a checkout is never sent to the reasoning endpoint."""
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    reasoning = _FakeBackend("from reasoning")
    services = replace(services, reasoning=_Reasoning(reasoning))
    store.create_card(WorkCard(
        id="card-1", workflow_id="wf-1", kind="analysis", title="Think",
        state="ready", eligible_roles=("developer",),
        workspace_permission=permission,
    ))
    agent = _FakeBackend("from the agent")

    await dispatch_ready_work(
        "wf-1", services, lambda _s: agent, timeout_seconds=5
    )

    assert (reasoning.last_request is not None) is reasons
    if reasons:
        assert agent.last_request is None
