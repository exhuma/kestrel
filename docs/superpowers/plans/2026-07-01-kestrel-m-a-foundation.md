# M-A · Kestrel Foundation & Rename — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the project to kestrel, put SQLite persistence behind
the existing in-memory session registry, and add the model-selection
policy module — with the spike mechanic still working end-to-end.

**Architecture:** Pure groundwork, no new behaviour. The in-memory
`SessionRegistry` becomes a write-through cache over SQLAlchemy tables
migrated by Alembic. A small `ModelPolicy` maps workflow-step names to
claude model aliases; `SessionRunner.build_argv` learns `--model`.
Nothing calls the policy yet (M-B's StepRunner will).

**Tech Stack:** Python 3.12+, FastAPI, pydantic-settings, SQLAlchemy
2.x, Alembic, SQLite, pytest; Vue 3 + Vuetify 4 (rename only).

## Global Constraints

- 80-character line limit, no lint suppressions.
- Backend: `uv` only (never `pip install`); `create_app()` factory;
  pydantic-settings `Settings`, env prefix becomes `KESTREL_`.
- Python: `from __future__ import annotations`, full type hints,
  Sphinx-style docstrings on all public symbols, no `Any`, never the
  `global` keyword.
- No `Base.metadata.create_all()` in app code; schema changes go
  through Alembic migrations only. No raw DDL strings in Python.
- Frontend: `npm` only; `<script setup lang="ts">`.
- Tests: pytest in `backend/tests/`, docstrings start with "Ensure …".
- All `uv`/`alembic`/`pytest` commands run from `backend/`.

---

### Task 1: Rename to kestrel

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml:2`
- Modify: `frontend/package.json:2`
- Modify: `frontend/src/App.vue:7-9`
- Test: `backend/tests/test_config.py` (new)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `Settings` reading the `KESTREL_` env prefix with
  `workspace_root: str = "./.kestrel-workspaces"`. All later tasks
  assume this prefix.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_config.py`:

```python
"""Tests for application settings."""
from __future__ import annotations

import pytest

from app.config import Settings


def test_settings_read_kestrel_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure settings read the KESTREL_ environment prefix."""
    monkeypatch.setenv("KESTREL_CLAUDE_BIN", "/opt/claude")
    assert Settings().claude_bin == "/opt/claude"


def test_workspace_default_is_kestrel_branded() -> None:
    """Ensure the default workspace root is kestrel-branded."""
    assert Settings().workspace_root == "./.kestrel-workspaces"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: both FAIL (`claude_bin == "claude"` because the env var is
ignored under the old `DISPATCHER_` prefix; old workspace default).

- [ ] **Step 3: Apply the rename**

`backend/app/config.py` — replace the class body's config and default:

```python
class Settings(BaseSettings):
    """Runtime configuration for the kestrel backend."""

    model_config = SettingsConfigDict(
        env_prefix="KESTREL_", env_file=".env"
    )

    claude_bin: str = "claude"
    workspace_root: str = "./.kestrel-workspaces"
    permission_mode: str = "acceptEdits"
```

`backend/app/main.py` — module docstring and title:

```python
"""FastAPI application factory for kestrel."""
```

```python
    app = FastAPI(title="kestrel")
```

`backend/pyproject.toml` — line 2:

```toml
name = "kestrel-backend"
```

`frontend/package.json` — line 2:

```json
  "name": "kestrel-frontend",
```

`frontend/src/App.vue` — app bar:

```vue
    <v-app-bar color="primary" title="kestrel">
      <template #prepend>
        <img src="/logo.svg" alt="kestrel logo" height="40"
          class="ms-2" />
      </template>
    </v-app-bar>
```

- [ ] **Step 4: Sweep remaining user-facing mentions**

Run: `grep -rni dispatcher --include='*.py' --include='*.ts' \
--include='*.vue' --include='*.toml' --include='*.json' \
--include='*.md' backend frontend README.md AGENTS.md 2>/dev/null`

For each hit in code or top-level docs, replace the wording with
kestrel (docstrings like "the dispatcher backend" → "the kestrel
backend"). Leave `docs/superpowers/` history documents untouched —
they describe the spike as it was. Also update the repo `.gitignore`:
ensure it contains these two lines (add them; drop a
`.dispatcher-workspaces` line if present):

```gitignore
.kestrel-workspaces/
kestrel.db
```

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `uv run pytest -v` and `cd ../frontend && npm test`
Expected: all PASS (no test asserts the old names).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename project to kestrel"
```

---

### Task 2: Persistence scaffolding (SQLAlchemy + Alembic)

**Files:**
- Modify: `backend/pyproject.toml` (deps)
- Modify: `backend/app/config.py` (add `database_url`)
- Create: `backend/app/persistence/__init__.py`
- Create: `backend/app/persistence/db.py`
- Create: `backend/app/persistence/tables.py`
- Create: `backend/alembic.ini`, `backend/alembic/` (via
  `alembic init`), `backend/alembic/versions/0001_initial.py`
- Test: `backend/tests/test_persistence.py` (new)

**Interfaces:**
- Consumes: `Settings` with `KESTREL_` prefix (Task 1).
- Produces:
  - `Settings.database_url: str = "sqlite:///./kestrel.db"`.
  - `app.persistence.db.get_engine() -> Engine` (lru_cached),
    `get_sessionmaker() -> sessionmaker[Session]` (lru_cached).
  - ORM rows `SessionRow(session_id: str [pk], cwd: str,
    status: str)` and `EventRow(id: int [pk], session_id: str [fk],
    type: str, raw: str)` in `app.persistence.tables`, plus `Base`.
  - Alembic migration `0001` creating both tables; applied with
    `uv run alembic upgrade head`.

- [ ] **Step 1: Add dependencies**

```bash
uv add "sqlalchemy>=2.0" "alembic>=1.13"
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_persistence.py`:

```python
"""Tests for the persistence layer and migrations."""
from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config


def _migrate(db_path: Path) -> str:
    """Apply all migrations to a fresh SQLite file."""
    url = f"sqlite:///{db_path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return url


def test_migrations_create_tables(tmp_path: Path) -> None:
    """Ensure migrations create the session and event tables."""
    url = _migrate(tmp_path / "test.db")
    inspector = sa.inspect(sa.create_engine(url))
    names = set(inspector.get_table_names())
    assert {"session", "event"} <= names
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: FAIL (`alembic.ini` does not exist).

- [ ] **Step 4: Add settings field and DB module**

`backend/app/config.py` — add below `permission_mode`:

```python
    database_url: str = "sqlite:///./kestrel.db"
```

Create `backend/app/persistence/__init__.py`:

```python
"""Durable storage: engine, tables, and write-through store."""
```

Create `backend/app/persistence/db.py`:

```python
"""Database engine and session factory."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """
    Return the process-wide database engine.

    :returns: The cached SQLAlchemy engine.
    """
    url = get_settings().database_url
    connect_args: dict[str, bool] = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, connect_args=connect_args)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """
    Return the process-wide DB session factory.

    :returns: The cached sessionmaker bound to the engine.
    """
    return sessionmaker(bind=get_engine())
```

Create `backend/app/persistence/tables.py`:

```python
"""ORM table definitions for kestrel."""
from __future__ import annotations

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    """Declarative base for all kestrel tables."""


class SessionRow(Base):
    """One dispatched claude session."""

    __tablename__ = "session"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    cwd: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column()


class EventRow(Base):
    """One parsed stream-json event belonging to a session."""

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("session.session_id")
    )
    type: Mapped[str] = mapped_column()
    raw: Mapped[str] = mapped_column(Text)
```

- [ ] **Step 5: Initialise Alembic and write migration 0001**

```bash
uv run alembic init alembic
```

Replace `backend/alembic/env.py` with:

```python
"""Alembic environment wiring kestrel settings and metadata."""
from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import Settings
from app.persistence.tables import Base

config = context.config
# Respect a URL injected by tests/CLI; otherwise read settings
# fresh (no lru_cache) so stale caches cannot leak between runs.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option(
        "sqlalchemy.url", Settings().database_url
    )
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

In the generated `backend/alembic.ini`, keep the generated logging
sections as-is but make sure the `[alembic]` section contains (and
contains no hard-coded `sqlalchemy.url` value):

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
sqlalchemy.url =
```

Create `backend/alembic/versions/0001_initial.py`:

```python
"""Initial session and event tables.

Revision ID: 0001
Revises:
Create Date: 2026-07-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the session and event tables."""
    op.create_table(
        "session",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("cwd", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
    )
    op.create_table(
        "event",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("session.session_id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    """Drop the event and session tables."""
    op.drop_table("event")
    op.drop_table("session")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add sqlalchemy/alembic persistence scaffolding"
```

---

### Task 3: Write-through store behind the registry

**Files:**
- Create: `backend/app/persistence/store.py`
- Modify: `backend/app/storage/registry.py`
- Test: `backend/tests/test_persistence.py` (extend)

**Interfaces:**
- Consumes: `get_sessionmaker()`, `SessionRow`, `EventRow` (Task 2);
  `ParsedEvent`, `SessionRecord` from `app.models` (existing).
- Produces:
  - `SessionStore(factory)` with `save_session(record)`,
    `set_status(session_id, status)`,
    `append_event(session_id, event)`,
    `load_all() -> list[SessionRecord]`; singleton `get_store()`.
  - `SessionRegistry(store: SessionStore | None = None)` — same
    public API as today, plus `preload(records)`; `get_registry()`
    now wires the store and preloads persisted sessions. M-B builds
    on exactly this registry API.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_persistence.py`:

```python
from app.models import ParsedEvent
from app.persistence.store import SessionStore
from app.storage.registry import SessionRegistry
from sqlalchemy.orm import sessionmaker


def _store(tmp_path: Path) -> SessionStore:
    url = _migrate(tmp_path / "store.db")
    factory = sessionmaker(bind=sa.create_engine(url))
    return SessionStore(factory)


def test_registry_survives_restart(tmp_path: Path) -> None:
    """Ensure sessions and events persist across registries."""
    store = _store(tmp_path)
    reg = SessionRegistry(store=store)
    reg.create("s1", "/tmp/s1")
    reg.append_event(
        "s1",
        ParsedEvent(
            type="assistant", session_id="s1", raw={"n": 1}
        ),
    )
    reg.set_status("s1", "idle")

    fresh = SessionRegistry(store=store)
    fresh.preload(store.load_all())
    rec = fresh.get("s1")
    assert rec is not None
    assert rec.cwd == "/tmp/s1"
    assert rec.status == "idle"
    assert [e.raw for e in rec.events] == [{"n": 1}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_persistence.py -v`
Expected: FAIL with `ModuleNotFoundError: app.persistence.store`.

- [ ] **Step 3: Implement the store**

Create `backend/app/persistence/store.py`:

```python
"""Write-through persistence for session records."""
from __future__ import annotations

import json
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import ParsedEvent, SessionRecord
from app.persistence.db import get_sessionmaker
from app.persistence.tables import EventRow, SessionRow


class SessionStore:
    """Persists session records and events to the database."""

    def __init__(
        self, factory: sessionmaker[Session]
    ) -> None:
        self._factory = factory

    def save_session(self, record: SessionRecord) -> None:
        """
        Insert a new session row.

        :param record: The freshly created session record.
        """
        with self._factory.begin() as db:
            db.add(
                SessionRow(
                    session_id=record.session_id,
                    cwd=record.cwd,
                    status=record.status,
                )
            )

    def set_status(
        self, session_id: str, status: str
    ) -> None:
        """
        Update a persisted session's status.

        :param session_id: Unique id of the session.
        :param status: The new status value.
        """
        with self._factory.begin() as db:
            row = db.get(SessionRow, session_id)
            if row is not None:
                row.status = status

    def append_event(
        self, session_id: str, event: ParsedEvent
    ) -> None:
        """
        Persist one parsed event.

        :param session_id: Unique id of the session.
        :param event: The parsed event to persist.
        """
        with self._factory.begin() as db:
            db.add(
                EventRow(
                    session_id=session_id,
                    type=event.type,
                    raw=json.dumps(event.raw),
                )
            )

    def load_all(self) -> list[SessionRecord]:
        """
        Load all sessions with their events, oldest first.

        :returns: Fully hydrated session records.
        """
        with self._factory() as db:
            records: list[SessionRecord] = []
            for row in db.scalars(select(SessionRow)):
                stmt = (
                    select(EventRow)
                    .where(
                        EventRow.session_id == row.session_id
                    )
                    .order_by(EventRow.id)
                )
                events = [
                    ParsedEvent(
                        type=e.type,
                        session_id=row.session_id,
                        raw=json.loads(e.raw),
                    )
                    for e in db.scalars(stmt)
                ]
                records.append(
                    SessionRecord(
                        session_id=row.session_id,
                        cwd=row.cwd,
                        status=row.status,
                        events=events,
                    )
                )
            return records


@lru_cache
def get_store() -> SessionStore:
    """
    Return the process-wide SessionStore singleton.

    :returns: The cached session store instance.
    """
    return SessionStore(get_sessionmaker())
```

- [ ] **Step 4: Wire the registry through the store**

In `backend/app/storage/registry.py`:

Change the imports and constructor:

```python
from app.models import ParsedEvent, SessionRecord
from app.persistence.store import SessionStore, get_store
```

```python
    def __init__(
        self, store: SessionStore | None = None
    ) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._subs: dict[
            str, list[asyncio.Queue[ParsedEvent]]
        ] = {}
        self._store = store
```

Add write-through calls (end of the existing methods):

```python
    # in create(), before `return record`:
        if self._store is not None:
            self._store.save_session(record)
```

```python
    # in append_event(), after the subscriber loop:
        if self._store is not None:
            self._store.append_event(session_id, event)
```

```python
    # in set_status(), inside the `is not None` branch:
            if self._store is not None:
                self._store.set_status(session_id, status)
```

Add `preload` and rewire the singleton:

```python
    def preload(
        self, records: list[SessionRecord]
    ) -> None:
        """
        Seed the registry with persisted records.

        Does not write back to the store.

        :param records: Records loaded from persistence.
        """
        for record in records:
            self._records[record.session_id] = record
            self._subs.setdefault(record.session_id, [])
```

```python
@lru_cache
def get_registry() -> SessionRegistry:
    """
    Return the process-wide SessionRegistry singleton.

    Preloads all persisted sessions so history survives
    restarts. Requires migrations to have been applied
    (``uv run alembic upgrade head``).

    :returns: The cached session registry instance.
    """
    store = get_store()
    registry = SessionRegistry(store=store)
    registry.preload(store.load_all())
    return registry
```

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -v`
Expected: all PASS. Existing registry tests still pass because
`store=None` keeps the old in-memory behaviour.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: persist sessions and events behind the registry"
```

---

### Task 4: Model-selection policy + `--model` support

**Files:**
- Create: `backend/app/policy.py`
- Modify: `backend/app/config.py` (add `model_overrides`)
- Modify: `backend/app/services/runner.py` (`build_argv`)
- Test: `backend/tests/test_policy.py` (new),
  `backend/tests/test_runner.py` (extend)

**Interfaces:**
- Consumes: `Settings` (Task 1).
- Produces:
  - `Settings.model_overrides: dict[str, str] = {}` (env:
    `KESTREL_MODEL_OVERRIDES='{"plan": "opus"}'`).
  - `app.policy.DEFAULT_MODELS` and
    `ModelPolicy.model_for(step: str) -> str`; singleton
    `get_policy()`. Step names: `gap_analysis`, `clarify`,
    `describe`, `plan`, `implement`.
  - `SessionRunner.build_argv(prompt, resume_id=None, model=None)`
    appending `--model <alias>` when given. M-B's StepRunner calls
    `get_policy().model_for(step)` and passes the result through.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_policy.py`:

```python
"""Tests for the model-selection policy."""
from __future__ import annotations

import pytest

from app.policy import DEFAULT_MODELS, ModelPolicy


def test_defaults_have_no_opus() -> None:
    """Ensure the default policy never selects opus."""
    assert "opus" not in DEFAULT_MODELS.values()


def test_model_for_uses_defaults() -> None:
    """Ensure known steps resolve to their default model."""
    policy = ModelPolicy(overrides={})
    assert policy.model_for("gap_analysis") == "haiku"
    assert policy.model_for("implement") == "sonnet"


def test_overrides_win() -> None:
    """Ensure configured overrides replace defaults."""
    policy = ModelPolicy(overrides={"plan": "opus"})
    assert policy.model_for("plan") == "opus"


def test_unknown_step_raises() -> None:
    """Ensure unknown steps fail loudly."""
    policy = ModelPolicy(overrides={})
    with pytest.raises(KeyError):
        policy.model_for("nonsense")
```

Append to `backend/tests/test_runner.py` (match the existing test
style in that file for constructing the runner):

```python
def test_build_argv_appends_model() -> None:
    """Ensure build_argv adds --model when one is given."""
    runner = SessionRunner(Settings(), SessionRegistry())
    argv = runner.build_argv("hi", model="sonnet")
    i = argv.index("--model")
    assert argv[i + 1] == "sonnet"


def test_build_argv_omits_model_by_default() -> None:
    """Ensure build_argv omits --model when not given."""
    runner = SessionRunner(Settings(), SessionRegistry())
    assert "--model" not in runner.build_argv("hi")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_policy.py tests/test_runner.py -v`
Expected: policy tests FAIL with `ModuleNotFoundError`; the two new
runner tests FAIL with `TypeError` (unexpected keyword `model`).

- [ ] **Step 3: Implement policy and runner change**

Create `backend/app/policy.py`:

```python
"""Model-selection policy mapping workflow steps to models."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings

#: Default step -> model map (spec SRD 2.7). Opus is never on
#: the default path; enable it per step via
#: ``KESTREL_MODEL_OVERRIDES``.
DEFAULT_MODELS: dict[str, str] = {
    "gap_analysis": "haiku",
    "clarify": "haiku",
    "describe": "sonnet",
    "plan": "sonnet",
    "implement": "sonnet",
}


class ModelPolicy:
    """Resolves which claude model a workflow step uses."""

    def __init__(self, overrides: dict[str, str]) -> None:
        self._map = {**DEFAULT_MODELS, **overrides}

    def model_for(self, step: str) -> str:
        """
        Return the model alias for a workflow step.

        :param step: Workflow step name, e.g. ``"plan"``.
        :returns: Alias to pass to ``claude --model``.
        :raises KeyError: If the step is unknown.
        """
        return self._map[step]


@lru_cache
def get_policy() -> ModelPolicy:
    """
    Return the process-wide ModelPolicy singleton.

    :returns: The cached model policy instance.
    """
    return ModelPolicy(get_settings().model_overrides)
```

`backend/app/config.py` — add below `database_url`:

```python
    model_overrides: dict[str, str] = {}
```

`backend/app/services/runner.py` — extend `build_argv`:

```python
    def build_argv(
        self,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
    ) -> list[str]:
        """
        Build the claude CLI argument vector.

        :param prompt: The prompt text to pass to claude.
        :param resume_id: Session id to resume, or None to
            start a new session.
        :param model: Model alias for ``--model``, or None to
            use the CLI's default.
        :returns: The argument vector for the subprocess.
        """
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
        if model is not None:
            argv += ["--model", model]
        if resume_id is not None:
            argv += ["--resume", resume_id]
        return argv
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add model-selection policy and --model support"
```

---

### Task 5: End-to-end verification & docs

**Files:**
- Modify: `backend/README.md` (or create if missing)
- Modify: `docs/superpowers/plans/kestrel-roadmap.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a verified M-A milestone; documented migrate/run steps.

- [ ] **Step 1: Document run steps**

Ensure `backend/README.md` contains a "Running" section:

````markdown
## Running

```bash
cd backend
uv run alembic upgrade head   # apply schema migrations
uv run uvicorn app.main:app --reload
```

Config via `KESTREL_*` env vars or `backend/.env`
(`KESTREL_DATABASE_URL`, `KESTREL_CLAUDE_BIN`,
`KESTREL_WORKSPACE_ROOT`, `KESTREL_PERMISSION_MODE`,
`KESTREL_MODEL_OVERRIDES`).
````

- [ ] **Step 2: Full automated verification**

Run: `cd backend && uv run alembic upgrade head && uv run pytest -v`
Run: `cd frontend && npm test`
Expected: migrations apply cleanly to `kestrel.db`; all tests PASS.

- [ ] **Step 3: Manual E2E (spike mechanic still works)**

1. Start backend (`uv run uvicorn app.main:app`) and frontend
   (`npm run dev`).
2. In the UI, start a session with a trivial prompt (e.g. "write a
   haiku to haiku.txt"); watch events stream; note the session id.
3. Restart the backend process.
4. Reload the UI: the session must still be listed with its full
   event history (loaded from SQLite), and Resume must work on it.

Expected: identical behaviour to the spike, plus history surviving
the restart.

- [ ] **Step 4: Tick the milestone and commit**

Mark M-A done in `docs/superpowers/plans/kestrel-roadmap.md` (checkbox
+ status log row with today's date).

```bash
git add -A
git commit -m "docs: verify and close milestone M-A"
```
