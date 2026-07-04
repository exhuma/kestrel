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
the bundled `claude` CLI, so no configuration is needed. To add backends
(self-hosted LLMs, opencode), write a **TOML file** and point kestrel at it:

```bash
KESTREL_BACKENDS_FILE=backends.toml   # relative to the working dir, or absolute
```

Copy [`backends.toml.example`](backends.toml.example) to `backends.toml` and
edit. It declares the available backends, the ad-hoc-session default, and the
per-workflow-step assignments:

```toml
default_session_backend = "local"

[step_backends]           # step -> backend id; omitted steps use the default
implement = "claude"      # keep implement on claude (see the opencode note)

[[backends]]
id = "claude"
type = "claude_cli"

[[backends]]
id = "local"
type = "openai_compat"    # a self-hosted OpenAI-compatible LLM
base_url = "http://localhost:11434/v1"
model = "llama3.1:8b"
```

Config is read once at startup — **restart the backend after editing it**. On
boot the effective config is logged (`backends: … | ad-hoc sessions dispatch
to: …`), and `GET /api/backends` reports it live. In Docker, mount the file and
set the env var (see the commented lines in `docker-compose.yml`).

> Without `KESTREL_BACKENDS_FILE` you can instead set `KESTREL_BACKENDS` (JSON),
> `KESTREL_DEFAULT_SESSION_BACKEND`, and `KESTREL_STEP_BACKENDS` (JSON) directly
> — but the file is easier to get right. The file supersedes these when set.

**Where backends apply.** Ad-hoc sessions (the **Sessions** panel /
`POST /api/sessions`) use `default_session_backend`. Each GitHub-workflow step
(`refine`, `plan`, `implement`) uses its `step_backends` entry if set, else the
same default. A step only accepts a backend that can satisfy it: `implement`
needs file-editing (`claude`/`opencode`), while `refine`/`plan` need only text
— so a plain LLM may serve them (it just won't read the repo). A bad mapping
(e.g. a text-only LLM on `implement`) fails that run with a clear capability
error.

The `openai_compat` backend is **text-only** (no file edits or tools); kestrel
owns the conversation history and replays it each turn.

The `opencode` backend is a full file-editing agent reached over
[`opencode serve`](https://opencode.ai/docs/server/). Start the server
separately (`opencode serve --port 4096`), point `base_url` at it, and set
`model` as `provider/model`:

```toml
[[backends]]
id = "oc"
type = "opencode"
base_url = "http://localhost:4096"
model = "anthropic/claude-sonnet-4"
```

For a **secured** server (one started with `OPENCODE_SERVER_PASSWORD`), give the
password so kestrel can send HTTP Basic auth (username defaults to `opencode`;
override with `username`). Put it inline via `password` — the config file is
gitignored — or, to keep it out of the file, use `api_key_env` naming an env
var you **export** in kestrel's process:

```toml
[[backends]]
id = "oc"
type = "opencode"
base_url = "http://localhost:4096"
model = "opencode/deepseek-v4-flash-free"
password = "changeme"                      # inline (gitignored file), or:
# api_key_env = "OPENCODE_SERVER_PASSWORD"  # name of an exported env var
```

Its sessions run in the directory where `opencode serve` was started —
opencode has no per-session working directory. That's fine for ad-hoc
sessions, but means opencode is **not yet suitable for the workflow
`implement` step**, which needs the agent to edit a per-run cloned workspace;
keep `implement` on `claude` (which honours the workspace). Live
token-streaming (via opencode's `/event` SSE) and an auto-started `serve`
supervisor are still in progress.

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
