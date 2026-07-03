# kestrel

Dispatch and monitor [Claude Code](https://github.com/anthropics/claude-code)
CLI sessions from a web UI. Kestrel is a single-user tool: a FastAPI backend
spawns `claude` sessions in per-run workspaces, persists them to SQLite, and
streams events over SSE to a Vue 3 / Vuetify frontend.

> **Status: alpha.** Interfaces and data formats may change between releases.

## Quickstart (Docker)

The published image bundles the backend, the built SPA, and the `claude` CLI in
one container. Authentication reuses your **host** Claude login, mounted into
the container.

```bash
# 1. Make sure you're logged in to Claude on the host (creates ~/.claude):
claude   # (run once, log in, then quit)

# 2. Fetch docker-compose.yml from the release and start it:
docker compose up
```

Then open <http://localhost:8000>.

`docker-compose.yml` mounts:

- a named volume at `/data` — the SQLite DB and session workspaces persist
  across restarts;
- your host `~/.claude` (read-only) — so the bundled CLI is authenticated.

### Configuration

Optional environment variables (see `docker-compose.yml`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `KESTREL_GITHUB_TOKEN` | _(empty)_ | Token for GitHub ingestion features |
| `KESTREL_PERMISSION_MODE` | `acceptEdits` | Permission mode for spawned sessions |
| `KESTREL_MODEL_OVERRIDES` | `{}` | JSON map of model overrides |

State locations inside the container are fixed by the image
(`KESTREL_DATABASE_URL`, `KESTREL_WORKSPACE_ROOT`, `KESTREL_STATIC_DIR`) and
normally need no changes.

## Running from source (development)

```bash
# Backend (http://localhost:8000)
cd backend
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Frontend (Vite dev server, separate terminal)
cd frontend
npm install
npm run dev
```

See `backend/README.md` for backend details.

## Versioning & releases

Releases use **CalVer**: `vYYYY.M.D` with an optional pre-release suffix
(`-alpha.N`, `-beta.N`, `-rc.N`) — e.g. `v2026.7.3-alpha.1`. Pushing such a tag
builds and publishes the image to `ghcr.io/exhuma/kestrel`.

Each release publishes the immutable full version (e.g. `2026.7.3-alpha.1`)
plus **moving channel pointers** that cascade by maturity — there is
deliberately **no `latest`** tag:

| Release kind | Channels advanced |
| --- | --- |
| `-alpha.N` | `alpha` |
| `-beta.N` | `beta`, `alpha` |
| `-rc.N` | `rc` |
| _(stable, no suffix)_ | `stable`, `beta`, `alpha` |

Track the alpha channel with `ghcr.io/exhuma/kestrel:alpha`.

## License

[MIT](LICENSE).
