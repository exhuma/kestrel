"""One OpenAI-compatible chat call per turn, with no tools and no files.

:class:`ReasoningClient` answers the same ``run_turn`` call an agent
backend does, so the board's callers do not change. What can go wrong is
told apart: a timeout raises :class:`TimeoutError`, a lost connection
:class:`~app.backends.base.BackendUnavailable`, the provider's content
filter :class:`ReasoningBlocked`, and anything else
:class:`~app.backends.base.BackendTurnError`.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.backends.base import (
    BackendTurnError,
    BackendUnavailable,
    TurnRequest,
    TurnResult,
)
from app.backends.limiter import BackendLimiter
from app.backends.rate_limit import retry_rate_limited
from app.config_reasoning import ReasoningEndpoint

_log = logging.getLogger("kestrel.reasoning")

_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_BACKOFF_SECONDS = 2.0
#: What the provider says when its content filter stopped the call.
_FILTERED = frozenset({"content_filter", "content_policy_violation"})
_CONNECTION_LOST = (
    httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError,
    httpx.WriteError,
)


class ReasoningBlocked(BackendTurnError):
    """The provider's content filter blocked the call or its answer."""


@dataclass(frozen=True)
class ReasoningTarget:
    """Who is reasoning, and where.

    :param role: The specialist role the call is for, for the log.
    :param endpoint: The endpoint and model to call.
    """

    role: str
    endpoint: ReasoningEndpoint


class ReasoningClient:
    """Runs one role's reasoning turns on its endpoint."""

    def __init__(
        self,
        target: ReasoningTarget,
        limiter: BackendLimiter,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = f"reasoning:{target.role}"
        self._target = target
        self._limiter = limiter
        self._client = client  # injectable for tests

    async def run_turn(
        self,
        req: TurnRequest,
        on_queue_change: Callable[[bool], None] | None = None,
    ) -> TurnResult:
        """Answer *req*'s prompt; ``cwd`` and permissions are ignored,
        since a reasoning turn has no files and no tools."""
        session_id = f"rsn-{uuid.uuid4().hex[:12]}"
        if req.on_session_id is not None:
            req.on_session_id(session_id)
        async with self._limiter.slot(on_queue_change):
            started = time.monotonic()
            data = await self._complete(req.prompt)
        text = _answer(data)
        self._log_call(session_id, req.card_id, data, started)
        return TurnResult(session_id=session_id, final_text=text)

    async def check_health(self) -> bool:
        """Whether the endpoint answers an authenticated model listing."""
        endpoint = self._target.endpoint
        async with self._session() as client:
            response = await client.get(
                f"{endpoint.base_url.rstrip('/')}/models",
                headers=self._headers(),
            )
        return response.status_code < httpx.codes.BAD_REQUEST

    async def _complete(self, prompt: str) -> dict:
        try:
            return await retry_rate_limited(
                lambda: self._post(prompt),
                _RATE_LIMIT_RETRIES, _RATE_LIMIT_BACKOFF_SECONDS,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError("the reasoning endpoint timed out") from exc
        except _CONNECTION_LOST as exc:
            raise BackendUnavailable(
                f"reasoning endpoint unreachable: {type(exc).__name__}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise _refusal(exc.response) from exc

    async def _post(self, prompt: str) -> dict:
        endpoint = self._target.endpoint
        async with self._session() as client:
            response = await client.post(
                f"{endpoint.base_url.rstrip('/')}/chat/completions",
                headers=self._headers(),
                json={
                    "model": endpoint.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise BackendTurnError("the reasoning endpoint did not answer")
        return data

    def _session(self) -> _Borrowed | httpx.AsyncClient:
        """The injected client, or a fresh one closed after the call."""
        if self._client is not None:
            return _Borrowed(self._client)
        endpoint = self._target.endpoint
        return httpx.AsyncClient(
            timeout=endpoint.timeout_seconds, verify=endpoint.verify_ssl
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._target.endpoint.api_key()}"}

    def _log_call(
        self, session_id: str, card_id: str | None, data: dict,
        started: float,
    ) -> None:
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        _log.info(
            "reasoning turn finished: session=%s role=%s card=%s model=%s "
            "seconds=%.1f prompt_tokens=%s completion_tokens=%s",
            session_id, self._target.role, card_id or "-",
            self._target.endpoint.model, time.monotonic() - started,
            usage.get("prompt_tokens"), usage.get("completion_tokens"),
        )


class _Borrowed:
    """An injected client used as ``async with``, without closing it."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _answer(data: dict) -> str:
    """The first choice's text, or why there is none."""
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, dict):
        raise BackendTurnError("the reasoning endpoint gave no answer")
    if choice.get("finish_reason") in _FILTERED:
        raise ReasoningBlocked(
            "the AI provider's content filter blocked the answer"
        )
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise BackendTurnError("the reasoning endpoint gave no answer")
    return content


def _refusal(response: httpx.Response) -> BackendTurnError:
    """What an error response means: a filter block, or a failure."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        error = None
    code = error.get("code") if isinstance(error, dict) else None
    if code in _FILTERED:
        return ReasoningBlocked(
            "the AI provider's content filter blocked the request"
        )
    return BackendTurnError(
        f"the reasoning endpoint answered HTTP {response.status_code}"
    )
