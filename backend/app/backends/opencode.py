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
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator, Callable

import httpx

from app.backends.base import Backend, Capability, TurnRequest, TurnResult
from app.config import BackendConfig, Settings
from app.models import CanonicalEvent, EventKind
from app.storage.registry import SessionRegistry

_TASKS: set[asyncio.Task[None]] = set()
_DEFAULT_TIMEOUT = 600.0  # a file-editing turn can run for minutes

#: File-mutating opencode tools. On a read-only step (refine, plan) these are
#: both disabled per message AND their permission requests are rejected, so
#: the agent cannot modify the workspace (defense-in-depth).
_DENY_WRITE_TOOLS = frozenset({"edit", "write", "patch"})

#: The claude-style permission mode that means "read-only, no edits". The
#: workflow passes this for the refine and plan steps; opencode maps it to a
#: read-only turn. Anything else is treated as edit-capable.
_READ_ONLY_MODE = "plan"


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
        self._timeout = cfg.timeout or _DEFAULT_TIMEOUT
        self._live: dict[str, asyncio.Task[None]] = {}
        # HTTP Basic auth for a secured `opencode serve`; username defaults
        # to opencode's own. The password may be given inline (password/
        # api_key) or via api_key_env.
        password = cfg.secret()
        self._auth = (
            httpx.BasicAuth(cfg.username or "opencode", password)
            if password
            else None
        )

    # ---- Backend protocol ---------------------------------------------
    async def start(self, prompt: str) -> str:
        cwd = os.path.join(
            self.settings.workspace_root, "session-" + uuid.uuid4().hex[:8]
        )
        # opencode resolves file tools against this directory; make sure it
        # exists (an ad-hoc session has no repo cloned into it yet).
        os.makedirs(cwd, exist_ok=True)
        sid = await self._create_session(cwd)
        self.registry.create(sid, cwd)
        # Ad-hoc sessions are user-driven and edit-capable.
        self._schedule(sid, prompt, cwd, read_only=False)
        return sid

    async def resume(self, session_id: str, prompt: str) -> str:
        # opencode keeps the session server-side; another message resumes it.
        self._schedule(
            session_id,
            prompt,
            self._session_dir(session_id),
            read_only=False,
        )
        return session_id

    async def run_turn(
        self,
        req: TurnRequest,
        on_session_id: Callable[[str], None] | None = None,
    ) -> TurnResult:
        sid = req.resume_id or await self._create_session(req.cwd)
        if self.registry.get(sid) is None:
            self.registry.create(sid, req.cwd)
        if on_session_id is not None:
            on_session_id(sid)
        read_only = req.permission_mode == _READ_ONLY_MODE
        content = await self._turn(sid, req.prompt, req.cwd, read_only)
        return TurnResult(session_id=sid, final_text=content)

    def terminate(self, session_id: str) -> bool:
        task = self._live.get(session_id)
        if task is not None and not task.done():
            task.cancel()
            return True
        return False

    # ---- internals ----------------------------------------------------
    def _session_dir(self, session_id: str) -> str | None:
        """Return the working directory recorded for a session, if any."""
        record = self.registry.get(session_id)
        return record.cwd if record is not None else None

    # ---- permissions --------------------------------------------------
    @asynccontextmanager
    async def _permission_handler(
        self, session_id: str, directory: str | None, read_only: bool
    ) -> AsyncIterator[None]:
        """Answer opencode permission prompts for the duration of a turn.

        opencode's permissions are ``ask`` by default, so a headless turn
        would block on the first tool call. A background task streams the
        server's ``/event`` bus and replies to each ``permission.asked`` for
        this session so the turn proceeds unattended.
        """
        task = asyncio.create_task(
            self._permission_loop(session_id, directory, read_only)
        )
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    async def _permission_loop(
        self, session_id: str, directory: str | None, read_only: bool
    ) -> None:
        """Stream ``/event`` and answer this session's permission prompts."""
        client = self._client or httpx.AsyncClient(timeout=None)
        params = (
            {"directory": os.path.abspath(directory)} if directory else None
        )
        try:
            async with client.stream(
                "GET",
                f"{self._base_url}/event",
                params=params,
                auth=self._auth,
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line[len("data:") :].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") != "permission.asked":
                        continue
                    props = event.get("properties") or {}
                    if props.get("sessionID") != session_id:
                        continue
                    await self._answer_permission(props, directory, read_only)
        except asyncio.CancelledError:
            raise
        except Exception:  # never let permission handling break the turn
            pass
        finally:
            if self._client is None:
                await client.aclose()

    async def _answer_permission(
        self,
        request: dict[str, object],
        directory: str | None,
        read_only: bool,
    ) -> None:
        """Approve or reject a single opencode permission request.

        Rejects a file-mutating tool on a read-only turn (defense-in-depth
        alongside the disabled tools); approves everything else — including
        ``bash``. Approving shell execution inside the workspace is a
        deliberate, documented prompt-injection risk in this alpha.
        """
        request_id = request.get("id")
        tool = request.get("permission")
        if not isinstance(request_id, str):
            return
        reject = read_only and tool in _DENY_WRITE_TOOLS
        with suppress(Exception):
            await self._request(
                "POST",
                f"/permission/{request_id}/reply",
                json={"reply": "reject" if reject else "once"},
                directory=directory,
            )

    def _schedule(
        self,
        session_id: str,
        prompt: str,
        directory: str | None,
        read_only: bool,
    ) -> None:
        task = asyncio.create_task(
            self._safe_turn(session_id, prompt, directory, read_only)
        )
        self._live[session_id] = task
        _TASKS.add(task)

        def _done(t: asyncio.Task[None]) -> None:
            _TASKS.discard(t)
            if self._live.get(session_id) is t:
                self._live.pop(session_id, None)

        task.add_done_callback(_done)

    async def _safe_turn(
        self,
        session_id: str,
        prompt: str,
        directory: str | None,
        read_only: bool,
    ) -> None:
        try:
            await self._turn(session_id, prompt, directory, read_only)
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

    async def _turn(
        self, session_id: str, prompt: str, directory: str | None,
        read_only: bool,
    ) -> str:
        """Send the prompt, map this turn's new messages, append a RESULT.

        A turn produces several assistant messages (tool calls then a final
        text message); the synchronous ``POST /message`` returns only the
        last one, so the full transcript is read from ``GET /message`` and
        the messages that are new since before the prompt are mapped.
        Snapshotting before the prompt keeps this correct across resumes
        and process restarts (existing history is not re-emitted).

        ``directory`` scopes every request to the session's working folder
        (the checked-out repo) so opencode's file tools act there rather than
        in the ``opencode serve`` process's own cwd.

        On a ``read_only`` turn the file-mutating tools are disabled for the
        message so the agent cannot edit the workspace. Throughout the turn a
        concurrent handler answers opencode's permission prompts (approve
        reads/bash, reject edits on a read-only turn) so a headless server
        never blocks waiting for a human to click "allow".
        """
        seen = {
            self._msg_id(m)
            for m in await self._messages(session_id, directory)
        }
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.USER_TEXT, session_id=session_id, text=prompt
            ),
        )
        body: dict[str, object] = {"parts": [{"type": "text", "text": prompt}]}
        if self._model is not None:
            body["model"] = self._model
        if read_only:
            body["tools"] = {tool: False for tool in _DENY_WRITE_TOOLS}
        async with self._permission_handler(
            session_id, directory, read_only
        ):
            await self._request(
                "POST",
                f"/session/{session_id}/message",
                json=body,
                directory=directory,
            )
        texts: list[str] = []
        for message in await self._messages(session_id, directory):
            if self._msg_role(message) != "assistant":
                continue  # user echo — we already emitted USER_TEXT
            if self._msg_id(message) in seen:
                continue  # from an earlier turn
            texts += self._emit_parts(session_id, self._msg_parts(message))
        final = "\n".join(t for t in texts if t)
        self.registry.append_event(
            session_id,
            CanonicalEvent(
                kind=EventKind.RESULT, session_id=session_id, text=final
            ),
        )
        return final

    async def _messages(
        self, session_id: str, directory: str | None = None
    ) -> list[dict]:
        """Fetch the full message transcript for a session."""
        data = await self._request(
            "GET", f"/session/{session_id}/message", directory=directory
        )
        if not isinstance(data, list):
            return []
        return [m for m in data if isinstance(m, dict)]

    @staticmethod
    def _msg_id(message: dict) -> str | None:
        info = message.get("info")
        return info.get("id") if isinstance(info, dict) else None

    @staticmethod
    def _msg_role(message: dict) -> str | None:
        info = message.get("info")
        return info.get("role") if isinstance(info, dict) else None

    @staticmethod
    def _msg_parts(message: dict) -> list[object]:
        parts = message.get("parts")
        return parts if isinstance(parts, list) else []

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
                raw_state = part.get("state")
                state = raw_state if isinstance(raw_state, dict) else {}
                tool_input = state.get("input")
                raw_tool = part.get("tool")
                self.registry.append_event(
                    session_id,
                    CanonicalEvent(
                        kind=EventKind.TOOL_USE,
                        session_id=session_id,
                        tool_name=(
                            raw_tool if isinstance(raw_tool, str) else None
                        ),
                        tool_input=(
                            tool_input if isinstance(tool_input, dict) else None
                        ),
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

    async def _create_session(self, directory: str | None = None) -> str:
        """Create an opencode session and return its id."""
        data = await self._request(
            "POST", "/session", json={}, directory=directory
        )
        sid = data.get("id") if isinstance(data, dict) else None
        if not isinstance(sid, str):
            raise RuntimeError("opencode did not return a session id")
        return sid

    async def _request(
        self,
        method: str,
        path: str,
        json: object | None = None,
        directory: str | None = None,
    ) -> object:
        """Issue one HTTP request against the opencode server.

        When ``directory`` is set it is sent as the ``directory`` query
        parameter, which opencode resolves the request's project directory
        from (query > ``x-opencode-directory`` header > the server's own
        cwd). Without it opencode would act in the ``opencode serve`` cwd.

        The directory is resolved to an **absolute** path first: opencode is
        a separate process with its own cwd (kestrel's workspace root is
        relative by default), so a relative path would resolve against the
        wrong base.
        """
        params = (
            {"directory": os.path.abspath(directory)} if directory else None
        )
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                params=params,
                auth=self._auth,
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._client is None:
                await client.aclose()
