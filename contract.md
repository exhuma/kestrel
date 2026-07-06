# Project Contract

Agent-dispatcher: a personal, single-user service that spawns coding-agent
sessions (Claude Code CLI) and monitors them from a web UI.

## Stack
- Backend: FastAPI (Python, uv) in `backend/`.
- Frontend: Vue 3 + Vuetify 4 + TypeScript (Vite, npm) in `frontend/`.

## Worker agent
- The backend invokes the host's logged-in `claude` CLI as a subprocess
  (Max subscription, OAuth). No `ANTHROPIC_API_KEY`; no Agent SDK.

## Scope and deliberate deviations
Single-user by design. For the architecture and history, see
[`docs/architecture.md`](docs/architecture.md); this section records the
constraints an agent must honour when changing the code.

- **No auth.** Single concurrent user; the API is unprotected. A shared-secret
  access gate is the only planned protection (see `docs/next-steps.md`), not
  multi-user auth.
- **State is persisted in SQLite** via SQLAlchemy 2.x, with the schema owned by
  Alembic (`backend/alembic/`). Never `create_all` or emit raw DDL from app
  code. Two deliberate departures from the usual FastAPI/SQLAlchemy patterns:
  - Stores own their `Session` lifecycle (a `sessionmaker(...).begin()` context
    per operation); there is **no** request-scoped `get_db` dependency. This
    fits the single-user write-through store and keeps persistence out of the
    router signatures.
  - Timestamps are stored as naive UTC `DateTime`. Acceptable while everything
    runs in one process/zone; revisit if timestamps are ever compared across
    zones.
- **Two run modes.** It ships as a Docker image (bundles backend + built SPA +
  the `claude` CLI) and also runs from source (uv / vite) for development. The
  backend reaches the host's logged-in `claude` and its `~/.claude` OAuth
  credentials (mounted into the container).

## Type contract
- Frontend business types in `frontend/src/types/` mirror the backend
  JSON shapes (`SessionSummary`, `SessionEvent`). Keep them in sync when
  the API changes.
