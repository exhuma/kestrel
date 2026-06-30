# Agent-Dispatcher Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove a long-running FastAPI dispatcher can spawn a `claude -p`
session, stream its events to a Vue/Vuetify browser view, and resume that
exact session with new human input.

**Architecture:** FastAPI backend spawns the host `claude` CLI as an
asyncio subprocess (`--output-format stream-json`), parses the JSONL event
stream into an in-memory registry, and fans events out to the browser over
SSE. A Vue 3 + Vuetify SPA starts/resumes sessions and renders the live
event log. Worker billing rides the host's Max subscription (OAuth login);
no API key.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, pydantic-settings, uv,
pytest + pytest-asyncio, httpx; Vue 3, Vuetify 4, TypeScript, Vite, npm,
vitest.

## Global Constraints

- **80-character line limit** for all files (Python, TS, Markdown, YAML,
  TOML). Enforced by linters; do not suppress.
- **Backend package manager: `uv` only.** Never `pip install`. Add deps
  with `uv add`. `pyproject.toml` is the source of truth. Venv at
  `backend/.venv`.
- **Frontend package manager: `npm` only.** Never yarn/pnpm/bun.
  `package.json` is the source of truth.
- **Python style:** Sphinx-style docstrings on every public module,
  class, function. Every source file has a module-level docstring. Full
  type annotations incl. return types. `from __future__ import
  annotations`. Avoid `Any`. All imports at module top level. **Never use
  the `global` keyword** — use `functools.lru_cache`-backed dependencies.
- **FastAPI:** build the app in a `create_app()` factory; register
  routers/handlers/middleware only inside it. All config via a
  `pydantic-settings` `Settings` class (`app/config.py`) with
  `env_prefix="DISPATCHER_"`; never read `os.environ`/`os.getenv`
  directly. Strict layering, calls only downward:
  `routers/ -> services/ -> storage/`. No business logic in routers.
- **Vue:** `<script setup lang="ts">` only (Options API prohibited). No
  `.js` under `src/`. No Pinia/Vuex — shared state via module-level
  singleton composables. No axios — vanilla `fetch` through a central
  `src/api/index.ts` exposing `api.get/post/put/delete`, an `ApiError`
  class, and a `setTokenProvider`/`TokenProvider` auth seam (present even
  though this spike has no auth). Business types under `src/types/`.
  Vuetify theme colours only — no hex/`rgb()`/named CSS colours. Components
  target < ~150 lines.
- **Tests:** backend pytest in `backend/tests/`, every test docstring
  starts with "Ensure …", `pytest-asyncio` for async. Frontend vitest in
  `frontend/tests/` mirroring `src/`; mock all HTTP, never real calls.
- **contract.md** exists at repo root; never contradict it.
- **Spike deviations (documented in contract.md):** runs on the host, not
  Docker/devcontainer (backend needs the host `claude` binary + OAuth).
  In-memory state only (no DB). No auth. Single user. One happy path.

---

### Task 1: Backend scaffold, settings, app factory

**Files:**
- Create: `contract.md`
- Create: `backend/pyproject.toml` (via `uv init`)
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_main.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `app.config.Settings` (fields `claude_bin: str`,
  `workspace_root: str`, `permission_mode: str`); `app.config.get_settings()
  -> Settings` (lru_cached). `app.main.create_app() -> FastAPI`;
  `app.main.app`. Root route `GET /` returns `{"status": "ok"}`.

- [ ] **Step 1: Write contract.md**

```markdown
# Project Contract

Agent-dispatcher: a personal, single-user service that spawns coding-agent
sessions (Claude Code CLI) and monitors them from a web UI.

## Stack
- Backend: FastAPI (Python, uv) in `backend/`.
- Frontend: Vue 3 + Vuetify 4 + TypeScript (Vite, npm) in `frontend/`.

## Worker agent
- The backend invokes the host's logged-in `claude` CLI as a subprocess
  (Max subscription, OAuth). No `ANTHROPIC_API_KEY`; no Agent SDK.

## Spike scope and deliberate deviations
- Runs directly on the host (uv / vite dev), NOT in Docker or a
  devcontainer — the backend must reach the host `claude` binary and its
  `~/.claude` OAuth credentials. Dockerisation is deferred.
- State is in-memory only. No database, no auth, single concurrent user.
- One hard-coded happy path (start a session, resume it).

## Type contract
- Frontend business types in `frontend/src/types/` mirror the backend
  JSON shapes (`SessionSummary`, `SessionEvent`). Keep them in sync when
  the API changes.
```

- [ ] **Step 2: Scaffold the backend project**

Run:
```bash
cd backend && uv init --no-workspace --name agent-dispatcher-backend . \
  && uv add fastapi "uvicorn[standard]" pydantic-settings \
  && uv add --dev pytest pytest-asyncio httpx
```
Then delete any `backend/hello.py`/`backend/main.py` stub `uv init`
created. Create the `app/` and `tests/` package dirs with empty
`__init__.py` files.

- [ ] **Step 3: Write the failing test**

`backend/tests/test_main.py`:
```python
"""Tests for the application factory and root route."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app


@pytest.mark.asyncio
async def test_root_returns_ok() -> None:
    """Ensure the root route reports service status ok."""
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

Add to `backend/pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["."]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: app.main` (or `create_app`).

- [ ] **Step 5: Write config.py**

`backend/app/config.py`:
```python
"""Application configuration via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the dispatcher backend."""

    model_config = SettingsConfigDict(
        env_prefix="DISPATCHER_", env_file=".env"
    )

    claude_bin: str = "claude"
    workspace_root: str = "./.dispatcher-workspaces"
    permission_mode: str = "acceptEdits"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton."""
    return Settings()
```

- [ ] **Step 6: Write main.py**

`backend/app/main.py`:
```python
"""FastAPI application factory for the agent dispatcher."""
from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="agent-dispatcher")

    @app.get("/")
    async def root() -> dict[str, str]:
        """Report basic service liveness."""
        return {"status": "ok"}

    return app


app = create_app()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 8: Update .gitignore and commit**

Append to root `.gitignore`:
```
backend/.venv/
backend/.dispatcher-workspaces/
backend/.env
__pycache__/
.pytest_cache/
```
```bash
git add contract.md backend/ .gitignore
git commit -m "feat(backend): scaffold FastAPI app factory and settings"
```

---

### Task 2: Event model and parser

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `app.models.ParsedEvent` (dataclass: `type: str`,
  `session_id: str | None`, `raw: dict[str, object]`);
  `app.models.parse_event(line: str) -> ParsedEvent | None` (returns None
  for blank/non-JSON lines); `app.models.SessionRecord` (dataclass:
  `session_id: str`, `cwd: str`, `status: str`,
  `events: list[ParsedEvent]`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_models.py`:
```python
"""Tests for event parsing and domain models."""
from __future__ import annotations

from app.models import ParsedEvent, parse_event


def test_parse_system_init_extracts_session_id() -> None:
    """Ensure the init event yields type and session id."""
    line = (
        '{"type":"system","subtype":"init",'
        '"session_id":"abc-123","tools":[]}'
    )
    ev = parse_event(line)
    assert isinstance(ev, ParsedEvent)
    assert ev.type == "system"
    assert ev.session_id == "abc-123"


def test_parse_result_event() -> None:
    """Ensure a result event parses with its session id."""
    line = (
        '{"type":"result","subtype":"success",'
        '"session_id":"abc-123","is_error":false}'
    )
    ev = parse_event(line)
    assert ev is not None
    assert ev.type == "result"
    assert ev.session_id == "abc-123"


def test_parse_event_without_session_id() -> None:
    """Ensure events without a session id parse with None."""
    ev = parse_event('{"type":"assistant","message":{}}')
    assert ev is not None
    assert ev.type == "assistant"
    assert ev.session_id is None


def test_parse_blank_or_garbage_returns_none() -> None:
    """Ensure blank or non-JSON lines are ignored."""
    assert parse_event("") is None
    assert parse_event("   ") is None
    assert parse_event("not json") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: app.models`.

- [ ] **Step 3: Write models.py**

`backend/app/models.py`:
```python
"""Domain models for sessions and parsed CLI events."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ParsedEvent:
    """A single parsed event from the claude stream-json output."""

    type: str
    session_id: str | None
    raw: dict[str, object]


@dataclass
class SessionRecord:
    """In-memory record of one dispatched session."""

    session_id: str
    cwd: str
    status: str = "running"
    events: list[ParsedEvent] = field(default_factory=list)


def parse_event(line: str) -> ParsedEvent | None:
    """
    Parse one JSONL line from the claude stream.

    :param line: A raw line of stream-json output.
    :returns: The parsed event, or None for blank/invalid lines.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    event_type = str(data.get("type", "unknown"))
    session_id = data.get("session_id")
    return ParsedEvent(
        type=event_type,
        session_id=session_id if isinstance(session_id, str) else None,
        raw=data,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_models.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat(backend): add event model and stream-json parser"
```

---

### Task 3: In-memory session registry with pub/sub

**Files:**
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/registry.py`
- Create: `backend/tests/test_registry.py`

**Interfaces:**
- Consumes: `app.models.ParsedEvent`, `app.models.SessionRecord`.
- Produces: `app.storage.registry.SessionRegistry` with methods
  `create(session_id: str, cwd: str) -> SessionRecord`,
  `get(session_id: str) -> SessionRecord | None`,
  `list() -> list[SessionRecord]`,
  `append_event(session_id: str, event: ParsedEvent) -> None`,
  `set_status(session_id: str, status: str) -> None`,
  `subscribe(session_id: str) -> asyncio.Queue[ParsedEvent]`,
  `unsubscribe(session_id: str, q: asyncio.Queue[ParsedEvent]) -> None`.
  `app.storage.registry.get_registry() -> SessionRegistry` (lru_cached).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_registry.py`:
```python
"""Tests for the in-memory session registry."""
from __future__ import annotations

import asyncio

import pytest

from app.models import ParsedEvent
from app.storage.registry import SessionRegistry


def _event(kind: str = "assistant") -> ParsedEvent:
    return ParsedEvent(type=kind, session_id="s1", raw={})


def test_create_get_list() -> None:
    """Ensure records can be created, fetched, and listed."""
    reg = SessionRegistry()
    rec = reg.create("s1", "/tmp/s1")
    assert rec.status == "running"
    assert reg.get("s1") is rec
    assert reg.get("missing") is None
    assert [r.session_id for r in reg.list()] == ["s1"]


def test_append_event_records_and_sets_status() -> None:
    """Ensure events accumulate and status can change."""
    reg = SessionRegistry()
    reg.create("s1", "/tmp/s1")
    reg.append_event("s1", _event())
    reg.set_status("s1", "idle")
    rec = reg.get("s1")
    assert rec is not None
    assert len(rec.events) == 1
    assert rec.status == "idle"


@pytest.mark.asyncio
async def test_subscribe_receives_appended_events() -> None:
    """Ensure subscribers receive events appended after subscribe."""
    reg = SessionRegistry()
    reg.create("s1", "/tmp/s1")
    q = reg.subscribe("s1")
    reg.append_event("s1", _event("result"))
    received = await asyncio.wait_for(q.get(), timeout=1.0)
    assert received.type == "result"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: app.storage.registry`.

- [ ] **Step 3: Write registry.py**

`backend/app/storage/registry.py`:
```python
"""In-memory registry of sessions with per-session pub/sub."""
from __future__ import annotations

import asyncio
from functools import lru_cache

from app.models import ParsedEvent, SessionRecord


class SessionRegistry:
    """Stores session records and broadcasts events to subscribers."""

    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._subs: dict[str, list[asyncio.Queue[ParsedEvent]]] = {}

    def create(self, session_id: str, cwd: str) -> SessionRecord:
        """Create and store a new running session record."""
        record = SessionRecord(session_id=session_id, cwd=cwd)
        self._records[session_id] = record
        self._subs.setdefault(session_id, [])
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        """Return the record for a session id, or None."""
        return self._records.get(session_id)

    def list(self) -> list[SessionRecord]:
        """Return all session records in insertion order."""
        return list(self._records.values())

    def append_event(
        self, session_id: str, event: ParsedEvent
    ) -> None:
        """Append an event and notify all live subscribers."""
        record = self._records.get(session_id)
        if record is None:
            return
        record.events.append(event)
        for q in self._subs.get(session_id, []):
            q.put_nowait(event)

    def set_status(self, session_id: str, status: str) -> None:
        """Update the status of an existing session record."""
        record = self._records.get(session_id)
        if record is not None:
            record.status = status

    def subscribe(
        self, session_id: str
    ) -> asyncio.Queue[ParsedEvent]:
        """Register and return a new subscriber queue."""
        q: asyncio.Queue[ParsedEvent] = asyncio.Queue()
        self._subs.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(
        self, session_id: str, q: asyncio.Queue[ParsedEvent]
    ) -> None:
        """Remove a subscriber queue if present."""
        subs = self._subs.get(session_id, [])
        if q in subs:
            subs.remove(q)


@lru_cache
def get_registry() -> SessionRegistry:
    """Return the process-wide SessionRegistry singleton."""
    return SessionRegistry()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_registry.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage backend/tests/test_registry.py
git commit -m "feat(backend): add in-memory session registry with pubsub"
```

---

### Task 4: Session runner (subprocess service)

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/runner.py`
- Create: `backend/tests/test_runner.py`

**Interfaces:**
- Consumes: `app.config.Settings`, `app.storage.registry.SessionRegistry`,
  `app.models.parse_event`.
- Produces: `app.services.runner.SessionRunner(settings, registry)` with:
  `build_argv(prompt: str, resume_id: str | None = None) -> list[str]`;
  `async consume(lines: AsyncIterator[str], cwd: str, record_id: str |
  None = None) -> str | None` (creates the record when the first
  session_id arrives if `record_id` is None, appends every event, sets
  status "idle" on a `result` event, returns the session id);
  `async start(prompt: str) -> str`; `async resume(session_id: str,
  prompt: str) -> str`. `app.services.runner.get_runner(...)` FastAPI
  dependency building a `SessionRunner`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_runner.py`:
```python
"""Tests for the session runner argv building and stream consume."""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from app.config import Settings
from app.services.runner import SessionRunner
from app.storage.registry import SessionRegistry


def _runner() -> SessionRunner:
    settings = Settings(
        claude_bin="claude",
        workspace_root="/tmp/ws",
        permission_mode="acceptEdits",
    )
    return SessionRunner(settings, SessionRegistry())


def test_build_argv_start() -> None:
    """Ensure start argv requests stream-json and permission mode."""
    argv = _runner().build_argv("hello")
    assert argv[:3] == ["claude", "-p", "hello"]
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv
    assert "--permission-mode" in argv
    assert "--resume" not in argv


def test_build_argv_resume() -> None:
    """Ensure resume argv includes the session id."""
    argv = _runner().build_argv("again", resume_id="s9")
    assert "--resume" in argv
    assert argv[argv.index("--resume") + 1] == "s9"


async def _lines(items: list[str]) -> AsyncIterator[str]:
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_consume_creates_record_and_sets_idle() -> None:
    """Ensure consume registers the session and finishes idle."""
    runner = _runner()
    lines = [
        '{"type":"system","subtype":"init","session_id":"s1"}',
        '{"type":"assistant","message":{}}',
        '{"type":"result","subtype":"success","session_id":"s1"}',
    ]
    sid = await runner.consume(_lines(lines), cwd="/tmp/ws/s1")
    assert sid == "s1"
    rec = runner.registry.get("s1")
    assert rec is not None
    assert rec.cwd == "/tmp/ws/s1"
    assert rec.status == "idle"
    assert len(rec.events) == 3


@pytest.mark.asyncio
async def test_consume_resume_appends_to_existing() -> None:
    """Ensure consume with record_id appends to the same record."""
    runner = _runner()
    runner.registry.create("s1", "/tmp/ws/s1")
    lines = [
        '{"type":"assistant","message":{}}',
        '{"type":"result","subtype":"success","session_id":"s1"}',
    ]
    sid = await runner.consume(
        _lines(lines), cwd="/tmp/ws/s1", record_id="s1"
    )
    assert sid == "s1"
    rec = runner.registry.get("s1")
    assert rec is not None
    assert len(rec.events) == 2
    assert rec.status == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.runner`.

- [ ] **Step 3: Write runner.py**

`backend/app/services/runner.py`:
```python
"""Service that spawns and resumes claude CLI sessions."""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from fastapi import Depends

from app.config import Settings, get_settings
from app.models import parse_event
from app.storage.registry import SessionRegistry, get_registry


class SessionRunner:
    """Spawns claude subprocesses and streams events to the registry."""

    def __init__(
        self, settings: Settings, registry: SessionRegistry
    ) -> None:
        self.settings = settings
        self.registry = registry

    def build_argv(
        self, prompt: str, resume_id: str | None = None
    ) -> list[str]:
        """Build the claude CLI argument vector."""
        argv = [
            self.settings.claude_bin,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            self.settings.permission_mode,
        ]
        if resume_id is not None:
            argv += ["--resume", resume_id]
        return argv

    async def consume(
        self,
        lines: AsyncIterator[str],
        cwd: str,
        record_id: str | None = None,
    ) -> str | None:
        """
        Consume a line stream, updating the registry.

        :param lines: Async iterator of raw JSONL lines.
        :param cwd: Working directory the session runs in.
        :param record_id: Existing record id (resume), or None to
            create a record when the first session id appears.
        :returns: The resolved session id, or None if never seen.
        """
        session_id = record_id
        async for line in lines:
            event = parse_event(line)
            if event is None:
                continue
            if session_id is None and event.session_id is not None:
                session_id = event.session_id
                self.registry.create(session_id, cwd)
            if session_id is not None:
                self.registry.append_event(session_id, event)
                if event.type == "result":
                    self.registry.set_status(session_id, "idle")
        return session_id

    async def _spawn(
        self, argv: list[str], cwd: str, record_id: str | None
    ) -> str:
        """Spawn the subprocess and drain its stdout via consume."""
        os.makedirs(cwd, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _stdout() -> AsyncIterator[str]:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                yield raw.decode("utf-8", "replace")

        sid = await self.consume(_stdout(), cwd, record_id)
        await proc.wait()
        if sid is None:
            raise RuntimeError("claude produced no session id")
        return sid

    async def start(self, prompt: str) -> str:
        """Start a new session and return its session id."""
        base = os.path.join(self.settings.workspace_root, "session")
        cwd = base + "-" + str(abs(hash(prompt)) % 10_000_000)
        argv = self.build_argv(prompt)
        return await self._spawn(argv, cwd, record_id=None)

    async def resume(self, session_id: str, prompt: str) -> str:
        """Resume an existing session with new input."""
        record = self.registry.get(session_id)
        if record is None:
            raise KeyError(session_id)
        argv = self.build_argv(prompt, resume_id=session_id)
        return await self._spawn(argv, record.cwd, record_id=session_id)


def get_runner(
    settings: Settings = Depends(get_settings),
    registry: SessionRegistry = Depends(get_registry),
) -> SessionRunner:
    """FastAPI dependency providing a SessionRunner."""
    return SessionRunner(settings, registry)
```

Note: `start`/`resume` await the full subprocess; the router (Task 5)
launches them as background tasks so requests return immediately while
events stream over SSE.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_runner.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services backend/tests/test_runner.py
git commit -m "feat(backend): add session runner with argv and consume"
```

---

### Task 5: Session routers and SSE endpoint

**Files:**
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/sessions.py`
- Modify: `backend/app/main.py` (register router + permissive CORS)
- Create: `backend/tests/test_sessions_router.py`

**Interfaces:**
- Consumes: `get_runner`, `get_registry`, `SessionRunner`,
  `SessionRegistry`.
- Produces routes: `POST /api/sessions {prompt}` -> `{session_id}` while
  scheduling `runner.start` as a background task (returns a provisional
  id `pending` is NOT used — instead the route awaits the first id; see
  step 3); `POST /api/sessions/{id}/resume {prompt}` -> `{session_id}`;
  `GET /api/sessions` -> `[{session_id,status,event_count}]`;
  `GET /api/sessions/{id}/events` -> SSE stream of JSON events (replays
  history, then live).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_sessions_router.py`:
```python
"""Tests for the sessions router (runner mocked)."""
from __future__ import annotations

import httpx
import pytest

from app.main import create_app
from app.models import ParsedEvent
from app.services.runner import SessionRunner, get_runner
from app.storage.registry import SessionRegistry, get_registry


class _FakeRunner(SessionRunner):
    """Runner that records a session without a real subprocess."""

    async def start(self, prompt: str) -> str:
        self.registry.create("fake-1", "/tmp/fake-1")
        self.registry.append_event(
            "fake-1", ParsedEvent("result", "fake-1", {})
        )
        self.registry.set_status("fake-1", "idle")
        return "fake-1"


def _client_with_fakes() -> tuple[httpx.AsyncClient, SessionRegistry]:
    app = create_app()
    registry = SessionRegistry()
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_runner] = lambda: _FakeRunner(
        None, registry  # type: ignore[arg-type]
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test"
    )
    return client, registry


@pytest.mark.asyncio
async def test_create_session_returns_id() -> None:
    """Ensure POST /api/sessions returns a session id."""
    client, _ = _client_with_fakes()
    async with client:
        resp = await client.post(
            "/api/sessions", json={"prompt": "hi"}
        )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "fake-1"


@pytest.mark.asyncio
async def test_list_sessions() -> None:
    """Ensure GET /api/sessions lists created sessions."""
    client, registry = _client_with_fakes()
    registry.create("s1", "/tmp/s1")
    async with client:
        resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    ids = [s["session_id"] for s in resp.json()]
    assert "s1" in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_sessions_router.py -v`
Expected: FAIL — cannot import `app.routers.sessions` / route 404.

- [ ] **Step 3: Write sessions.py**

`backend/app/routers/sessions.py`:
```python
"""HTTP routes for creating, listing, and streaming sessions."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.runner import SessionRunner, get_runner
from app.storage.registry import SessionRegistry, get_registry

router = APIRouter(prefix="/api")


class PromptIn(BaseModel):
    """Request body carrying a single prompt string."""

    prompt: str


class SessionOut(BaseModel):
    """Response body identifying a session."""

    session_id: str


@router.post("/sessions", response_model=SessionOut)
async def create_session(
    body: PromptIn,
    runner: SessionRunner = Depends(get_runner),
) -> SessionOut:
    """Start a new claude session and return its id."""
    session_id = await runner.start(body.prompt)
    return SessionOut(session_id=session_id)


@router.post("/sessions/{session_id}/resume", response_model=SessionOut)
async def resume_session(
    session_id: str,
    body: PromptIn,
    runner: SessionRunner = Depends(get_runner),
) -> SessionOut:
    """Resume an existing session with new input."""
    try:
        sid = await runner.resume(session_id, body.prompt)
    except KeyError as exc:
        raise HTTPException(404, "unknown session") from exc
    return SessionOut(session_id=sid)


@router.get("/sessions")
async def list_sessions(
    registry: SessionRegistry = Depends(get_registry),
) -> list[dict[str, object]]:
    """List all known sessions with status and event counts."""
    return [
        {
            "session_id": r.session_id,
            "status": r.status,
            "event_count": len(r.events),
        }
        for r in registry.list()
    ]


@router.get("/sessions/{session_id}/events")
async def stream_events(
    session_id: str,
    registry: SessionRegistry = Depends(get_registry),
) -> StreamingResponse:
    """Stream session events as Server-Sent Events."""

    async def _gen() -> AsyncIterator[bytes]:
        record = registry.get(session_id)
        if record is not None:
            for ev in list(record.events):
                yield _sse(ev.raw)
        q = registry.subscribe(session_id)
        try:
            while True:
                ev = await q.get()
                yield _sse(ev.raw)
        finally:
            registry.unsubscribe(session_id, q)

    return StreamingResponse(
        _gen(), media_type="text/event-stream"
    )


def _sse(payload: dict[str, object]) -> bytes:
    """Encode a payload as one SSE data frame."""
    return ("data: " + json.dumps(payload) + "\n\n").encode("utf-8")
```

Note on background execution: for the live happy path, change
`create_session`/`resume_session` to schedule the runner and return as
soon as the id is known. Implement by having the router call
`asyncio.create_task(runner.start(...))` and await a short
`registry`-backed signal. For the spike, the simplest correct option is
to keep `await runner.start(...)` (the init event arrives within the
first second, but the call returns only when the process exits). If the
UI feels blocked, switch `start`/`resume` to fire-and-forget tasks and
return the id via a `asyncio.Future` resolved inside `consume` when the
first id appears. Keep the blocking version unless step "Task 8" shows it
is a problem.

- [ ] **Step 4: Register the router and CORS in main.py**

Replace `backend/app/main.py` body with:
```python
"""FastAPI application factory for the agent dispatcher."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(title="agent-dispatcher")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root() -> dict[str, str]:
        """Report basic service liveness."""
        return {"status": "ok"}

    from app.routers import sessions

    app.include_router(sessions.router)
    return app


app = create_app()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest -v`
Expected: PASS (all tests, including prior tasks).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers backend/app/main.py \
  backend/tests/test_sessions_router.py
git commit -m "feat(backend): add session routes and SSE event stream"
```

---

### Task 6: Frontend scaffold (Vite + Vuetify + api seam)

**Files:**
- Create: `frontend/` (Vite vue-ts scaffold), `frontend/package.json`
- Create: `frontend/src/main.ts` (Vuetify theme, light + dark)
- Create: `frontend/src/api/index.ts`
- Create: `frontend/src/types/sessions.ts`
- Create: `frontend/tests/api/index.test.ts`
- Modify: root `.gitignore` (add `frontend/node_modules/`,
  `frontend/dist/`)

**Interfaces:**
- Produces: `api.get/post` (in `src/api/index.ts`), `ApiError`,
  `setTokenProvider`, `TokenProvider`; types `SessionSummary`
  (`session_id: string; status: string; event_count: number`) and
  `SessionEvent` (`type: string; session_id: string | null; raw:
  Record<string, unknown>`).

- [ ] **Step 1: Scaffold and add deps**

Run:
```bash
npm create vite@latest frontend -- --template vue-ts
cd frontend && npm install \
  && npm install vuetify @mdi/font \
  && npm install -D vitest
```

- [ ] **Step 2: Write the failing test**

`frontend/tests/api/index.test.ts`:
```typescript
import { describe, it, expect, vi, afterEach } from 'vitest'
import { api, ApiError } from '../../src/api'

afterEach(() => vi.restoreAllMocks())

describe('api', () => {
  it('returns parsed json on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      ),
    )
    const data = await api.get<{ ok: boolean }>('/x')
    expect(data.ok).toBe(true)
  })

  it('throws ApiError on non-2xx', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 500 })),
    )
    await expect(api.get('/x')).rejects.toBeInstanceOf(ApiError)
  })
})
```

Add to `frontend/package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `../../src/api`.

- [ ] **Step 4: Write the api module**

`frontend/src/api/index.ts`:
```typescript
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export interface TokenProvider {
  getToken(): string | null
}

let tokenProvider: TokenProvider = {
  getToken: () => localStorage.getItem('token'),
}

export function setTokenProvider(p: TokenProvider): void {
  tokenProvider = p
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public data: unknown,
  ) {
    super(`API error ${status}`)
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  const token = tokenProvider.getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const resp = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!resp.ok) {
    throw new ApiError(resp.status, await resp.text())
  }
  return (await resp.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) =>
    request<T>('POST', path, body),
}
```

`frontend/src/types/sessions.ts`:
```typescript
export interface SessionSummary {
  session_id: string
  status: string
  event_count: number
}

export interface SessionEvent {
  type: string
  session_id: string | null
  raw: Record<string, unknown>
}
```

- [ ] **Step 5: Write main.ts with Vuetify theme**

`frontend/src/main.ts`:
```typescript
import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'
import App from './App.vue'

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'dark',
    themes: {
      light: { dark: false, colors: { primary: '#1565C0' } },
      dark: { dark: true, colors: { primary: '#64B5F6' } },
    },
  },
})

createApp(App).use(vuetify).mount('#app')
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add frontend .gitignore
git commit -m "feat(frontend): scaffold Vuetify app with api seam"
```

---

### Task 7: Session UI and live SSE wiring

**Files:**
- Create: `frontend/src/composables/useSessions.ts`
- Create: `frontend/src/components/SessionPanel.vue`
- Modify: `frontend/src/App.vue`
- Create: `frontend/tests/composables/useSessions.test.ts`

**Interfaces:**
- Consumes: `api`, `SessionSummary`, `SessionEvent`.
- Produces: `useSessions()` returning `{ sessions, events, loading,
  refresh, start, resume, watchEvents }` (module-level singleton
  composable). `start(prompt: string): Promise<string>`;
  `resume(id: string, prompt: string): Promise<string>`;
  `watchEvents(id: string): void` (opens an `EventSource`).

- [ ] **Step 1: Write the failing test**

`frontend/tests/composables/useSessions.test.ts`:
```typescript
import { describe, it, expect, vi, afterEach } from 'vitest'
import { useSessions } from '../../src/composables/useSessions'

afterEach(() => vi.restoreAllMocks())

describe('useSessions', () => {
  it('refresh populates sessions from api', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify([
            { session_id: 's1', status: 'idle', event_count: 2 },
          ]),
          { status: 200 },
        ),
      ),
    )
    const { sessions, refresh } = useSessions()
    await refresh()
    expect(sessions.value.map((s) => s.session_id)).toContain('s1')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `useSessions`.

- [ ] **Step 3: Write the composable**

`frontend/src/composables/useSessions.ts`:
```typescript
import { ref } from 'vue'
import { api } from '../api'
import type { SessionEvent, SessionSummary } from '../types/sessions'

const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const sessions = ref<SessionSummary[]>([])
const events = ref<SessionEvent[]>([])
const loading = ref(false)

export function useSessions() {
  async function refresh(): Promise<void> {
    loading.value = true
    try {
      sessions.value = await api.get<SessionSummary[]>('/api/sessions')
    } finally {
      loading.value = false
    }
  }

  async function start(prompt: string): Promise<string> {
    const out = await api.post<{ session_id: string }>(
      '/api/sessions',
      { prompt },
    )
    await refresh()
    return out.session_id
  }

  async function resume(id: string, prompt: string): Promise<string> {
    const out = await api.post<{ session_id: string }>(
      `/api/sessions/${id}/resume`,
      { prompt },
    )
    await refresh()
    return out.session_id
  }

  function watchEvents(id: string): void {
    events.value = []
    const src = new EventSource(`${BASE}/api/sessions/${id}/events`)
    src.onmessage = (e) => {
      events.value.push(JSON.parse(e.data) as SessionEvent)
    }
  }

  return { sessions, events, loading, refresh, start, resume, watchEvents }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: Write SessionPanel.vue and App.vue**

`frontend/src/components/SessionPanel.vue`:
```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useSessions } from '../composables/useSessions'

const { sessions, events, loading, refresh, start, resume, watchEvents } =
  useSessions()
const prompt = ref('Write a haiku about the sea into poem.txt')
const followUp = ref('Now revise it to be about mountains instead.')
const current = ref<string | null>(null)

onMounted(refresh)

async function onStart(): Promise<void> {
  current.value = await start(prompt.value)
  watchEvents(current.value)
}

async function onResume(): Promise<void> {
  if (current.value) {
    await resume(current.value, followUp.value)
    watchEvents(current.value)
  }
}
</script>

<template>
  <v-container>
    <v-row>
      <v-col cols="4">
        <v-textarea v-model="prompt" label="Start prompt" rows="3" />
        <v-btn color="primary" block @click="onStart">Start</v-btn>
        <v-textarea
          v-model="followUp"
          label="Resume input"
          rows="3"
          class="mt-4"
        />
        <v-btn
          color="primary"
          block
          :disabled="!current"
          @click="onResume"
        >
          Resume
        </v-btn>
        <v-list>
          <v-list-item
            v-for="s in sessions"
            :key="s.session_id"
            :title="s.session_id"
            :subtitle="`${s.status} · ${s.event_count} events`"
          />
        </v-list>
      </v-col>
      <v-col cols="8">
        <v-card title="Live events">
          <v-card-text style="font-family: monospace">
            <div v-for="(e, i) in events" :key="i">
              {{ e.type }} — {{ JSON.stringify(e.raw).slice(0, 120) }}
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
    <v-progress-linear
      v-if="loading"
      absolute
      color="primary"
      indeterminate
      location="bottom"
    />
  </v-container>
</template>
```

`frontend/src/App.vue`:
```vue
<script setup lang="ts">
import SessionPanel from './components/SessionPanel.vue'
</script>

<template>
  <v-app>
    <v-app-bar color="primary" title="agent-dispatcher" />
    <v-main>
      <SessionPanel />
    </v-main>
  </v-app>
</template>
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src frontend/tests
git commit -m "feat(frontend): session panel with live SSE event log"
```

---

### Task 8: End-to-end happy-path verification (manual)

**Files:** none (verification + notes).

This task proves the spike's success criteria against the real `claude`
CLI on the host. It is not unit-tested; it is an observed run.

- [ ] **Step 1: Confirm host prerequisites**

Run: `claude --version` (works) and confirm `claude` is logged in on a
Max plan and `echo $ANTHROPIC_API_KEY` is empty (so billing uses the
subscription, not API tokens).

- [ ] **Step 2: Start the backend on the host**

Run: `cd backend && uv run uvicorn app.main:app --reload --port 8000`
Verify `curl localhost:8000/` returns `{"status":"ok"}`.

- [ ] **Step 3: Start the frontend**

Run: `cd frontend && npm run dev` and open `http://localhost:5173`.

- [ ] **Step 4: Run the happy path**

Click **Start** (haiku→poem.txt). Confirm: events stream into the live
log, a `system/init` event shows a `session_id`, and a `result` event
arrives. Note the session id in the session list (status `idle`).

- [ ] **Step 5: Resume the same session**

Click **Resume** (revise to mountains). Confirm: a new run streams under
the **same** session id and the agent edits the **existing** `poem.txt`
(proving cross-process session continuity). Check the file under the
session's workspace dir.

- [ ] **Step 6: Record results and commit notes**

Append a short "Spike results" section to
`docs/superpowers/specs/2026-06-30-agent-dispatcher-spike-design.md`
recording: confirmed/failed success criteria, the actual permission mode
that worked non-interactively, and the real `stream-json` event shapes
observed (so later iterations can rely on them).
```bash
git add docs/superpowers/specs/2026-06-30-agent-dispatcher-spike-design.md
git commit -m "docs: record agent-dispatcher spike results"
```

---

## Self-Review

- **Spec coverage:** spawn (Task 4/8), capture session_id (Task 2/4),
  resume same session (Task 4/5/8), live web view (Task 5/7/8),
  subscription billing (Task 8 step 1). FastAPI+Vue stack, in-memory, no
  auth, single user — all honoured. Out-of-scope items (GitHub, DB,
  webhooks, retries) intentionally absent.
- **Placeholder scan:** no TBD/TODO; all code blocks complete. The one
  judgement call (blocking vs background `start`) is documented with a
  concrete fallback, not left vague.
- **Type consistency:** `SessionRunner(settings, registry)`,
  `build_argv(prompt, resume_id)`, `consume(lines, cwd, record_id)`,
  registry method names, and frontend `session_id/status/event_count`
  shapes are consistent across tasks and match `src/types/sessions.ts`.
