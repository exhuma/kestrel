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

### Volumes

`docker-compose.yml` mounts four things:

| Mount | Mode | Purpose |
| --- | --- | --- |
| `kestrel-data` → `/data` | read-write | SQLite DB and the container's Claude `HOME`, persisted across restarts |
| `./workspaces` → `/workspaces` | read-write | The git repos claude clones and edits — **browsable on the host** |
| `~/.claude` → `/seed/.claude` | read-only | Seed: your host Claude config/plugins/credentials |
| `~/.claude.json` → `/seed/claude.json` | read-only | Seed: your host Claude config file (MCP servers, plugin state) |

On startup the container **copies** the two read-only seeds into its own
writable `HOME` (on the `/data` volume). It never writes back to your host
Claude config. Credentials are refreshed from the seed on every restart, so
re-logging-in on the host (`claude`) propagates after a `docker compose restart`.

### MCP servers & plugins

The spawned `claude` sessions pick up **your** user-level MCP servers and
plugins, because the container's `HOME` is seeded from your host `~/.claude` and
`~/.claude.json` (where those are configured). No extra setup is required beyond
the seed mounts above.

Supported MCP server runtimes are the ones bundled in the image: **node/npx**,
**uv/uvx**, **python**, and **git**. Not supported inside the container:

- MCP servers launched via **docker** or a **custom host binary** (those tools
  aren't in the image);
- servers or config that point at **host-absolute paths** that don't exist in
  the container;
- project-scoped `.mcp.json` servers may need to be **pre-approved** on the host
  first (approval state is read from the seeded `~/.claude.json`).

> **Alpha limitation.** MCP is the load-bearing piece and works (HTTP/stdio
> servers whose runtime is in the image connect fine). **Plugin _enablement_**,
> however, is per-config/per-project state carried in your seeded config — a
> plugin that isn't enabled for the spawned session's context on the host won't
> be active in the container either. Getting plugins to activate reliably in
> dispatched sessions is deferred; expect to iterate here post-alpha.

### Configuration

Optional environment variables (see `docker-compose.yml`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `KESTREL_GITHUB_TOKEN` | _(empty)_ | Token for GitHub ingestion features |
| `KESTREL_PERMISSION_MODE` | `acceptEdits` | Permission mode for spawned sessions |
| `KESTREL_MODEL_OVERRIDES` | `{}` | JSON map of model overrides |

Other state locations are set by the image (`KESTREL_DATABASE_URL`,
`KESTREL_STATIC_DIR`, `HOME`) and normally need no changes.
`KESTREL_WORKSPACE_ROOT` defaults to `/workspaces` to match the host bind mount
above.

### Backends (experimental)

Kestrel dispatches to a pluggable **backend**. By default the only backend is
the bundled `claude` CLI, so no configuration is needed. To make ad-hoc
sessions (the **Sessions** panel / `POST /api/sessions`) run on a different
system, declare backends as JSON and pick the default:

| Variable | Default | Purpose |
| --- | --- | --- |
| `KESTREL_BACKENDS` | `[{"id":"claude","type":"claude_cli"}]` | Available backends |
| `KESTREL_DEFAULT_SESSION_BACKEND` | `claude` | Backend for ad-hoc sessions |

A backend entry has `id`, `type` (`claude_cli` \| `openai_compat` \|
`opencode`), and per-type fields (`base_url`, `model`, `api_key_env`). Example —
route ad-hoc sessions to a self-hosted, OpenAI-compatible model (Ollama, vLLM,
LocalAI, …):

```bash
KESTREL_BACKENDS='[{"id":"claude","type":"claude_cli"},
  {"id":"local","type":"openai_compat",
   "base_url":"http://localhost:11434/v1","model":"llama3"}]'
KESTREL_DEFAULT_SESSION_BACKEND=local
```

The `openai_compat` backend is **text-only** (no file edits or tools); kestrel
owns the conversation history and replays it each turn. `opencode` and
per-workflow-step backend selection are in progress.

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
