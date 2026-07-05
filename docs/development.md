# Development (running from source)

For hacking on kestrel itself. To just *run* it, use the
[Docker image](getting-started.md) instead.

## Prerequisites

- **Python ≥ 3.12** with [uv](https://docs.astral.sh/uv/).
- **Node 22** with npm.
- The **`claude` CLI** on your `PATH`, logged in (the backend spawns it).
- **git** (the backend runs real git operations in session workspaces).

## Run

```bash
# Backend — API on http://localhost:8000
cd backend
uv run alembic upgrade head          # apply schema migrations
uv run uvicorn app.main:app --reload

# Frontend — Vite dev server, separate terminal
cd frontend
npm install
npm run dev
```

In development the backend is API-only (`KESTREL_STATIC_DIR` empty) and the
Vite dev server serves the UI; CORS already allows loopback origins. In the
packaged image the backend serves the built SPA itself.

`uvicorn app.main:app --reload` is fine for hot-reload, but its logs use
uvicorn's own format. To get the same **unified** logging the container uses
(uvicorn + app logs on one stream, `KESTREL_LOG_FORMAT`-aware), run the
package launcher instead — it supports reload too:

```bash
KESTREL_RELOAD=1 uv run python -m app        # unified logs + hot-reload
KESTREL_LOG_FORMAT=json uv run python -m app # structured logs
```

## Configuration

Copy `backend/.env.example` to `backend/.env` and edit. It is gitignored.
See [Configuration](configuration.md) for every `KESTREL_*` setting, and
[Backends](backends.md) for dispatching to opencode or a self-hosted LLM.

## Tests

```bash
# Backend
cd backend
uv run pytest

# Frontend (type-check + build, and unit tests)
cd frontend
npm run build
npm test
```

Backend tests are hermetic (they never read your `backend/.env`). The same
suite gates CI and every release.

## Project layout

| Path | Contents |
| --- | --- |
| `backend/app/` | FastAPI app: routers, services, persistence, SSE |
| `backend/app/backends/` | The pluggable backend adapters + registry |
| `backend/alembic/` | Database migrations |
| `frontend/src/` | Vue 3 + Vuetify SPA (composables, components, types) |
| `docs/` | This documentation |
| `docker/entrypoint.sh` | Container entrypoint (seed config, migrate, serve) |

For the bigger picture see [Architecture](architecture.md) and the design
notes under `docs/superpowers/specs/`.
