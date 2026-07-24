# Development (running from source)

For hacking on kestrel itself. To just *run* it, use the
[Docker image](getting-started.md) instead.

## Prerequisites

- **Python ≥ 3.12** with [uv](https://docs.astral.sh/uv/).
- **Node 22** with npm.
- The **`claude` CLI** on your `PATH`, logged in (the backend spawns it).
- **git** (the backend runs real git operations in session workspaces).

## Run

The quickest path is the [Taskfile](https://taskfile.dev) at the repo root
(install `task`, then):

```bash
task setup   # one-time: install backend + frontend deps, seed
             # backend/.env, apply migrations
task dev     # run the backend (:8000) and frontend (:5173) dev servers
```

Run `task --list` to see every task (`task backend` / `task frontend` run one
side on its own). The manual equivalents:

```bash
# Backend — API on http://localhost:8000
cd backend
uv run alembic upgrade head              # apply schema migrations
KESTREL_RELOAD=1 uv run python -m app    # unified logs + hot-reload

# Frontend — Vite dev server, separate terminal
cd frontend
npm install
npm run dev
```

In development the backend is API-only (`KESTREL_STATIC_DIR` empty) and the
Vite dev server serves the UI; CORS already allows loopback origins. In the
packaged image the backend serves the built SPA itself.

Prefer `python -m app` over invoking `uvicorn app.main:app --reload` directly.
Besides **unified** logging (uvicorn + app logs on one stream,
`KESTREL_LOG_FORMAT`-aware), it excludes the run workspace
(`KESTREL_WORKSPACE_ROOT`, `.kestrel-workspaces` by default) from the
auto-reloader. A run writes real `.py` files there (git clone, agent edits);
without the exclude, `--reload` restarts the whole server mid-run and drops
every open SSE connection (the sidebar/notification streams go blank with
`ERR_EMPTY_RESPONSE`).

```bash
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

For the bigger picture see [Architecture](architecture.md); the roadmap and
backlog live in the [GitHub issue tracker](https://github.com/exhuma/kestrel/issues).
