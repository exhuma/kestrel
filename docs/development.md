# Development (running from source)

For hacking on kestrel itself. To just *run* it, use the
[Docker image](getting-started.md) instead.

## Prerequisites

- **Python ≥ 3.12** with [uv](https://docs.astral.sh/uv/).
- **Node 22** with npm.
- The **`claude` CLI** on your `PATH`, logged in (the backend spawns it).
- **git** (the backend runs real git operations in session workspaces).
- **PostgreSQL** (13 or later): a server you may create databases on. Any
  local install or container works, for example:

  ```bash
  docker run -d --name kestrel-postgres -p 5432:5432 \
    -e POSTGRES_USER=kestrel -e POSTGRES_PASSWORD=kestrel \
    -e POSTGRES_DB=kestrel postgres:16
  ```

  That matches the `KESTREL_DATABASE_URL` in `backend/.env.example`.

## Run

The quickest path is the [Taskfile](https://taskfile.dev) at the repo root
(install `task`, then):

```bash
task setup   # one-time: install backend + frontend deps, seed
             # backend/.env, migrate the database it names
task dev     # run the backend (:8000) and frontend (:5173) dev servers
```

Run `task --list` to see every task (`task backend` / `task frontend` run one
side on its own). `task dev` selects root `config.toml`; its `port` setting
overrides the task's `KESTREL_PORT` fallback, and the frontend's API base must
match it. The manual equivalents:

```bash
# Backend — API on http://localhost:8000
cd backend
uv run alembic upgrade head              # apply schema migrations
uv run python -m app --reload            # unified logs + hot-reload

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
every open SSE connection (the sidebar streams go blank with
`ERR_EMPTY_RESPONSE`).

```bash
KESTREL_LOG_FORMAT=json uv run python -m app # structured logs
```

## Configuration

Copy `backend/.env.example` to `backend/.env` and edit. It is gitignored.
`KESTREL_DATABASE_URL` is required: kestrel does not start without a
database. To empty the database, run `task local-tasks:reset-db`, which
rebuilds its schema.
See [Configuration](configuration.md) for every `KESTREL_*` setting, and
[Backends](backends.md) for dispatching to opencode.

## Tests

```bash
# Backend: needs a PostgreSQL server (see Prerequisites)
cd backend
export KESTREL_TEST_DATABASE_URL=postgresql+psycopg://kestrel:kestrel@localhost:5432/kestrel
uv run pytest

# Frontend (type-check + build, and unit tests)
cd frontend
npm run build
npm test
```

Backend tests are hermetic (they never read your `backend/.env`).
`KESTREL_TEST_DATABASE_URL` names a server, not the database the tests use:
each run creates its own uniquely named databases there (one migrated
template, cloned for the tests that need a database of their own) and drops
them when it ends, so the user in the URL must be allowed to create
databases. Without the variable the run stops at once. The same suite gates
CI and every release.

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
