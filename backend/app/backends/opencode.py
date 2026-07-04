"""opencode backend, via its HTTP server (``opencode serve``).

A file-editing agent ({TEXT, FILE_EDITS}) reached over opencode's HTTP
API: a session is created with ``POST /session`` and a turn is run with
the synchronous ``POST /session/:id/message``, which blocks until the
assistant finishes and returns the full list of message ``parts``. Those
parts are mapped onto canonical events for the timeline.

Point ``base_url`` at a running ``opencode serve`` (default
``http://localhost:4096``). Live token-by-token streaming via the
server-wide ``/event`` SSE, and an auto-started ``serve`` supervisor,
are deferred; the synchronous turn already yields the full transcript.
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

_TASKS: set[asyncio.Task[None]] = set()
_DEFAULT_TIMEOUT = 600.0  # a file-editing turn can run for minutes


def _split_model(model: str | None) -> dict[str, str] | None:
    """Parse a ``provider/model`` string into opencode's model object."""
    if not model or "/" not in model:
        return None
    provider, _, model_id = model.partition("/")
    return {"providerID": provider, "modelID": model_id}


def _tool_summary(tool_input: object) -> str | None:
    """Summarise a tool call's input (file_path/path/command first)."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "command", "filePath"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return json.dumps(tool_input) if tool_input else None


class OpenCodeBackend(Backend):
    """Dispatches turns to an ``opencode serve`` HTTP endpoint."""

    caps = frozenset({Capability.TEXT, Capability.FILE_EDITS})

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
        self._base_url = (cfg.base_url or "http://localhost:4096").rstrip("/")
        self._model = _split_model(cfg.model)
        self._client = client  # injectable for tests
        self._live: dict[str, asyncio.Task[None]] = {}

    # ---- Backend protocol ---------------------------------------------
    async def start(self, prompt: str) -> str:
        sid = await self._create_session()
        cwd = os.path.join(
            self.settings.workspace_root, "session-" + uuid.uuid4().hex[:8]
        )
        self.registry.create(sid, cwd)
        self._schedule(sid, prompt)
        return sid

    async def resume(self, session_id: str, prompt: str) -> str:
        # opencode keeps the session server-side; another message resumes it.
        self._schedule(session_id, prompt)
        return session_id

    async def run_turn(
        self,
        req: TurnRequest,
        on_session_id: Callable[[str], None] | None = None,
    ) -> TurnResult:
        sid = req.resume_id or await self._create_session()
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
        task = asyncio.create_task(self._safe_turn(session_id, prompt))
        self._live[session_id] = task
        _TASKS.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            _TASKS.discard(t)
            if self._live.get(session_id) is t:
                self._live.pop(session_id, None)

        task.add_done_callback(_done)

    async def _safe_turn(self, session_id: str, prompt: str) -> None:
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
        """Send the prompt, map the returned parts, append a RESULT."""
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.USER_TEXT, session_id=session_id, text=prompt
            ),
        )
        body: dict[str, object] = {"parts": [{"type": "text", "text": prompt}]}
        if self._model is not None:
            body["model"] = self._model
        data = await self._request(
            "POST", f"/session/{session_id}/message", json=body
        )
        parts = data.get("parts") if isinstance(data, dict) else None
        texts = self._emit_parts(session_id, parts or [])
        final = "\n".join(texts)
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.RESULT, session_id=session_id, text=final
            ),
        )
        return final

    def _emit_parts(
        self, session_id: str, parts: list[object]
    ) -> list[str]:
        """Map opencode message parts to canonical events; return the texts."""
        texts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
                self.registry.append_event(
                    session_id,
                    CanonicalEvent(
                        kind=EventKind.ASSISTANT_TEXT,
                        session_id=session_id,
                        text=part["text"],
                        native=part,
                    ),
                )
            elif ptype == "tool":
                state = part.get("state") if isinstance(part.get("state"), dict) else {}
                tool_input = state.get("input")
                self.registry.append_event(
                    session_id,
                    CanonicalEvent(
                        kind=EventKind.TOOL_USE,
                        session_id=session_id,
                        tool_name=part.get("tool") if isinstance(part.get("tool"), str) else None,
                        tool_input=tool_input if isinstance(tool_input, dict) else None,
                        tool_summary=_tool_summary(tool_input),
                        native=part,
                    ),
                )
                output = state.get("output")
                if isinstance(output, str) and output:
                    self.registry.append_event(
                        session_id,
                        CanonicalEvent(
                            kind=EventKind.TOOL_RESULT,
                            session_id=session_id,
                            text=output,
                            is_error=state.get("status") == "error",
                            native=part,
                        ),
                    )
            elif ptype == "reasoning" and isinstance(part.get("text"), str):
                self.registry.append_event(
                    session_id,
                    CanonicalEvent(
                        kind=EventKind.SYSTEM,
                        session_id=session_id,
                        subtype="reasoning",
                        summary=part["text"],
                        native=part,
                    ),
                )
            # step-start / step-finish / snapshot / … are structural — skip.
        return texts

    async def _create_session(self) -> str:
        """Create an opencode session and return its id."""
        data = await self._request("POST", "/session", json={})
        sid = data.get("id") if isinstance(data, dict) else None
        if not isinstance(sid, str):
            raise RuntimeError("opencode did not return a session id")
        return sid

    async def _request(
        self, method: str, path: str, json: object | None = None
    ) -> object:
        """Issue one HTTP request against the opencode server."""
        client = self._client or httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)
        try:
            resp = await client.request(
                method, f"{self._base_url}{path}", json=json
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._client is None:
                await client.aclose()
