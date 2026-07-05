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
import json
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
        content = await self._complete(session_id, self._history(session_id))
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

    async def _complete(
        self, session_id: str, messages: list[dict[str, str]]
    ) -> str:
        """
        Stream the chat completion, emitting live activity as it goes.

        Requests a streaming response so a long local-model turn surfaces
        progress: a ``THINKING`` event once reasoning tokens appear (for
        reasoning-capable models — absent ones are simply skipped), a
        ``TOOL_USE`` event per tool the model calls, and a single
        ``SYSTEM`` "generating" marker when the answer text starts. These
        drive the chip's activity hint via ``activity_for``. An endpoint
        that ignores ``stream`` and returns a normal JSON body still works
        — it just yields no intermediate events.

        :returns: The assistant's full reply text.
        """
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {"model": self._model, "messages": messages, "stream": True}
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(
                        f"LLM endpoint {self._base_url} returned "
                        f"{resp.status_code} for model {self._model!r}"
                    )
                ctype = resp.headers.get("content-type", "")
                if "event-stream" in ctype:
                    return await self._consume_stream(session_id, resp)
                # Endpoint ignored `stream`: read the whole body and parse
                # it as a single (non-streaming) completion.
                body = await resp.aread()
                return self._content_of(json.loads(body))
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"LLM request to {self._base_url} timed out after "
                f"{self._timeout:.0f}s (model {self._model!r})"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"LLM request to {self._base_url} failed: {exc!r}"
            ) from exc
        finally:
            if self._client is None:
                await client.aclose()

    async def _consume_stream(
        self, session_id: str, resp: httpx.Response
    ) -> str:
        """Consume an SSE completion stream, emitting phase events.

        Emits at most one event per phase transition (not per token), so
        the event log and SSE stay coarse while the chip still updates.
        """
        reasoning_seen = False
        content_seen = False
        tools_seen: set[str] = set()
        parts: list[str] = []
        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            choices = chunk.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta")
            if not isinstance(delta, dict):
                continue
            reasoning = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
                or delta.get("thinking")
            )
            if reasoning and not reasoning_seen:
                reasoning_seen = True
                self.registry.append_event(
                    session_id,
                    CanonicalEvent(
                        kind=EventKind.THINKING, session_id=session_id
                    ),
                )
            for call in delta.get("tool_calls") or []:
                fn = call.get("function") if isinstance(call, dict) else None
                name = fn.get("name") if isinstance(fn, dict) else None
                if isinstance(name, str) and name and name not in tools_seen:
                    tools_seen.add(name)
                    self.registry.append_event(
                        session_id,
                        CanonicalEvent(
                            kind=EventKind.TOOL_USE, session_id=session_id,
                            tool_name=name,
                        ),
                    )
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                if not content_seen:
                    content_seen = True
                    self.registry.append_event(
                        session_id,
                        CanonicalEvent(
                            kind=EventKind.SYSTEM, session_id=session_id,
                            subtype="generating", summary="generating response",
                        ),
                    )
                parts.append(piece)
        return "".join(parts)

    def _content_of(self, data: object) -> str:
        """Extract the assistant text from a non-streaming JSON body."""
        try:
            return data["choices"][0]["message"]["content"]  # type: ignore[index]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"unexpected response from {self._base_url}: "
                f"{str(data)[:200]}"
            ) from exc
