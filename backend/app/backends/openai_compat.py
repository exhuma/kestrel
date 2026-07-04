"""Plain OpenAI-compatible LLM backend (ollama / vLLM / LocalAI / …).

A text-only backend: it produces LLM responses but does not edit files
or run tools, so it advertises only ``TEXT`` and cannot serve a step
that needs ``FILE_EDITS``. These endpoints have no server-side session,
so kestrel owns the conversation — reconstructed from the session's own
persisted ``USER_TEXT`` / ``ASSISTANT_TEXT`` canonical events, which
means history survives a restart with no extra storage.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Callable

import httpx

from app.backends.base import Backend, Capability, TurnRequest, TurnResult
from app.config import BackendConfig, Settings
from app.models import CanonicalEvent, EventKind
from app.storage.registry import SessionRegistry

# Strong references to in-flight streaming tasks (see runner._TASKS for why
# a per-request-free, process-lifetime hold is needed).
_TASKS: set[asyncio.Task[None]] = set()

_DEFAULT_TIMEOUT = 120.0  # local models can be slow to first token


class OpenAICompatBackend(Backend):
    """Dispatches turns to an OpenAI-compatible chat-completions endpoint."""

    caps = frozenset({Capability.TEXT})

    def __init__(
        self,
        settings: Settings,
        registry: SessionRegistry,
        cfg: BackendConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.id = cfg.id
        self.settings = settings
        self.registry = registry
        self._base_url = (cfg.base_url or "http://localhost:11434/v1").rstrip("/")
        self._model = cfg.model or "llama3"
        self._api_key = cfg.secret()
        self._timeout = cfg.timeout or _DEFAULT_TIMEOUT
        self._client = client  # injectable for tests
        self._live: dict[str, asyncio.Task[None]] = {}

    # ---- Backend protocol ---------------------------------------------
    async def start(self, prompt: str) -> str:
        sid = "llm-" + uuid.uuid4().hex[:8]
        cwd = os.path.join(
            self.settings.workspace_root, "session-" + uuid.uuid4().hex[:8]
        )
        self.registry.create(sid, cwd)
        self._schedule(sid, prompt)
        return sid

    async def resume(self, session_id: str, prompt: str) -> str:
        # SessionService has already verified the record exists.
        self._schedule(session_id, prompt)
        return session_id

    async def run_turn(
        self,
        req: TurnRequest,
        on_session_id: Callable[[str], None] | None = None,
    ) -> TurnResult:
        sid = req.resume_id or ("llm-" + uuid.uuid4().hex[:8])
        if self.registry.get(sid) is None:
            self.registry.create(sid, req.cwd)
        if on_session_id is not None:
            on_session_id(sid)
        content = await self._turn(sid, req.prompt)
        return TurnResult(session_id=sid, final_text=content)

    def terminate(self, session_id: str) -> bool:
        task = self._live.get(session_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    # ---- internals ----------------------------------------------------
    def _schedule(self, session_id: str, prompt: str) -> None:
        """Run a turn in the background, streaming events to the registry."""
        task = asyncio.create_task(self._safe_turn(session_id, prompt))
        self._live[session_id] = task
        _TASKS.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            _TASKS.discard(t)
            if self._live.get(session_id) is t:
                self._live.pop(session_id, None)

        task.add_done_callback(_done)

    async def _safe_turn(self, session_id: str, prompt: str) -> None:
        """Run a turn, surfacing any failure as a failed RESULT event."""
        try:
            await self._turn(session_id, prompt)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never leave the session stuck "running"
            self.registry.append_event(
                session_id,
                CanonicalEvent(
                    kind=EventKind.RESULT,
                    session_id=session_id,
                    is_error=True,
                    text=str(exc),
                ),
            )

    async def _turn(self, session_id: str, prompt: str) -> str:
        """Append the prompt, call the model, append the reply + result."""
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.USER_TEXT, session_id=session_id, text=prompt
            ),
        )
        content = await self._complete(self._history(session_id))
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.ASSISTANT_TEXT,
                session_id=session_id,
                text=content,
                model=self._model,
            ),
        )
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.RESULT, session_id=session_id, text=content
            ),
        )
        return content

    def _history(self, session_id: str) -> list[dict[str, str]]:
        """Rebuild the chat history from the session's persisted events."""
        record = self.registry.get(session_id)
        if record is None:
            return []
        messages: list[dict[str, str]] = []
        for event in record.events:
            if event.kind == EventKind.USER_TEXT:
                messages.append({"role": "user", "content": event.text or ""})
            elif event.kind == EventKind.ASSISTANT_TEXT:
                messages.append(
                    {"role": "assistant", "content": event.text or ""}
                )
        return messages

    async def _complete(self, messages: list[dict[str, str]]) -> str:
        """POST the chat history and return the assistant's reply text."""
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {"model": self._model, "messages": messages, "stream": False}
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"LLM request to {self._base_url} timed out after "
                f"{self._timeout:.0f}s (model {self._model!r})"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"LLM endpoint {self._base_url} returned "
                f"{exc.response.status_code} for model {self._model!r}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"LLM request to {self._base_url} failed: {exc!r}"
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"unexpected response from {self._base_url}: "
                f"{str(data)[:200]}"
            ) from exc
