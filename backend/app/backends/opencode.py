"""OpenCode HTTP server backend."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import httpx

from app.backends.base import (
    PERMISSION_READ_ONLY,
    Backend,
    Capability,
    ModelCatalog,
    TurnRequest,
    TurnResult,
    TurnStopped,
)
from app.backends.limiter import BackendLimiter
from app.backends.opencode_abort import abort_on_cancel
from app.backends.opencode_models import split_model
from app.backends.opencode_parts import assistant_error
from app.backends.opencode_permissions import (
    OpenCodeConnection,
    directory_params,
    permission_handler,
)
from app.backends.opencode_tools import (
    ToolLoopGuard,
    ToolPolicy,
    guard_watch,
    tools_map,
)
from app.backends.rate_limit import retry_rate_limited
from app.config import BackendConfig, Settings

_DEFAULT_TIMEOUT = 600.0  # a file-editing turn can run for minutes
_logger = logging.getLogger(__name__)


class OpenCodeBackend(Backend):
    """Dispatches turns to an ``opencode serve`` HTTP endpoint."""

    caps = frozenset({Capability.TEXT, Capability.FILE_EDITS})

    def __init__(
        self,
        settings: Settings,
        cfg: BackendConfig,
        client: httpx.AsyncClient | None = None,
        limiter: BackendLimiter | None = None,
    ) -> None:
        self.id = cfg.id
        self.settings = settings
        self._base_url = (cfg.base_url or "http://localhost:4096").rstrip("/")
        self._model = split_model(cfg.model)
        self._client = client  # injectable for tests
        self._timeout = cfg.timeout or _DEFAULT_TIMEOUT
        self._limiter = limiter or BackendLimiter(cfg.max_concurrency)
        self._rate_limit_retries = cfg.rate_limit_retries
        self._rate_limit_backoff_seconds = cfg.rate_limit_backoff_seconds
        self._tools = ToolPolicy.of(cfg)
        # HTTP Basic auth for a secured `opencode serve`; username defaults
        # to opencode's own. The password may be given inline (password/
        # api_key) or via api_key_env.
        password = cfg.secret()
        self._auth = (
            httpx.BasicAuth(cfg.username or "opencode", password)
            if password
            else None
        )
        self._conn = OpenCodeConnection(
            base_url=self._base_url,
            auth=self._auth,
            client=self._client,
            request=self._request,
        )

    async def run_turn(
        self,
        req: TurnRequest,
        on_queue_change: Callable[[bool], None] | None = None,
    ) -> TurnResult:
        async with self._limiter.slot(on_queue_change):
            return await self._run_turn(req)

    async def _run_turn(self, req: TurnRequest) -> TurnResult:
        """Run an admitted turn, logging any failure before re-raising."""
        sid: str | None = req.resume_id
        try:
            if sid is None:
                sid = await self._create_session(req.cwd)
            if req.on_session_id is not None:
                req.on_session_id(sid)
            content = await self._turn(sid, req)
            return TurnResult(session_id=sid, final_text=content)
        except asyncio.CancelledError:
            abort_on_cancel(self._request, sid, req.cwd)
            raise
        except Exception:
            _logger.exception(
                "opencode run_turn failed (session=%s, cwd=%s)", sid, req.cwd,
            )
            raise

    async def list_models(self) -> ModelCatalog:
        """Report unknown until OpenCode exposes a stable catalogue contract."""
        return ModelCatalog(state="unknown")

    async def _turn(self, session_id: str, req: TurnRequest) -> str:
        """Send the prompt and return the text of this turn's new messages.

        A turn produces several assistant messages (tool calls then a final
        text message); the synchronous ``POST /message`` returns only the
        last one, so the full transcript is read from ``GET /message`` and
        the messages that are new since before the prompt are read.
        Snapshotting before the prompt keeps this correct across resumes
        and process restarts (existing history is not re-read).

        ``directory`` scopes every request to the session's working folder
        (the checked-out repo) so opencode's file tools act there rather than
        in the ``opencode serve`` process's own cwd.

        Read-only turns disable write/delegation tools. A concurrent permission
        handler keeps headless turns from blocking on tool approval, and
        feeds the turn's tool calls to a loop guard that aborts it on a
        loop or past its tool budget (feature 036).
        """
        prompt, directory = req.prompt, req.cwd
        read_only = req.permission_mode == PERMISSION_READ_ONLY
        guard = ToolLoopGuard(self._tools, req.on_tool)
        seen = {
            self._msg_id(m)
            for m in await self._messages(session_id, directory)
        }
        body: dict[str, object] = {"parts": [{"type": "text", "text": prompt}]}
        if self._model is not None:
            body["model"] = self._model
        tools = tools_map(self._tools, read_only)
        if tools is not None:
            body["tools"] = tools
        async with permission_handler(
            self._conn, session_id, directory, read_only,
            guard_watch(self._conn, session_id, directory, guard),
        ):
            response = await retry_rate_limited(
                lambda: self._request(
                    "POST",
                    f"/session/{session_id}/message",
                    json=body,
                    directory=directory,
                ),
                self._rate_limit_retries,
                self._rate_limit_backoff_seconds,
            )
        if guard.tripped is not None:
            raise TurnStopped(guard.tripped)
        error = assistant_error(response)
        if error is not None:
            raise RuntimeError(f"opencode assistant failed: {error}")
        texts: list[str] = []
        for message in await self._messages(session_id, directory):
            if self._msg_role(message) != "assistant":
                continue  # user echo
            if self._msg_id(message) in seen:
                continue  # from an earlier turn
            texts += self._texts_of(self._msg_parts(message))
        return "\n".join(t for t in texts if t)

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

    @staticmethod
    def _texts_of(parts: list[object]) -> list[str]:
        """Collect the text of every ``text`` part (the turn's deliverable)."""
        return [
            part["text"]
            for part in parts
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]

    async def _create_session(self, directory: str | None = None) -> str:
        """Create an opencode session and return its id."""
        data = await self._request(
            "POST", "/session", json={}, directory=directory
        )
        sid = data.get("id") if isinstance(data, dict) else None
        if not isinstance(sid, str):
            _logger.warning(
                "opencode create-session returned no session id: %r", data
            )
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
        params = directory_params(directory)
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
        except Exception:
            _logger.warning(
                "opencode request failed: %s %s", method, path, exc_info=True,
            )
            raise
        finally:
            if self._client is None:
                await client.aclose()
