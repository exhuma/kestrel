# Configuration

Kestrel is configured entirely through `KESTREL_*` environment variables (or
a `backend/.env` file when running from source). Backends can additionally be
configured from a TOML file — see [Backends](backends.md).

## Environment variables

Every setting, with its default. Prefix is `KESTREL_`; the field name is the
lower-cased remainder (e.g. `KESTREL_GITHUB_TOKEN` → `github_token`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `KESTREL_CLAUDE_BIN` | `claude` | Path/name of the `claude` CLI to spawn |
| `KESTREL_WORKSPACE_ROOT` | `./.kestrel-workspaces` | Where per-session git workspaces are created (image: `/workspaces`) |
| `KESTREL_PERMISSION_MODE` | `acceptEdits` | Passed to `claude --permission-mode` for spawned sessions |
| `KESTREL_MODEL_OVERRIDES` | `{}` | JSON map of per-step model overrides, e.g. `{"sonnet":"claude-sonnet-5"}` |
| `KESTREL_GITHUB_TOKEN` | _(empty)_ | Token for GitHub ingestion (issues, clone/push, PRs). See [GitHub workflow](setup-github-workflow.md) |
| `KESTREL_GITHUB_API_BASE` | `https://api.github.com` | GitHub REST API base URL (override for GitHub Enterprise) |
| `KESTREL_GIT_BASE` | `https://github.com` | Base URL for git clones |
| `KESTREL_DATABASE_URL` | `sqlite:///./kestrel.db` | SQLAlchemy database URL (image: `sqlite:////data/kestrel.db`) |
| `KESTREL_STATIC_DIR` | _(empty)_ | Directory of the built SPA to serve. Empty = API-only (dev); the image sets it to the baked-in bundle |
| `KESTREL_BACKENDS_FILE` | _(empty)_ | Path to a TOML backend config. Recommended way to configure backends — see [Backends](backends.md) |
| `KESTREL_BACKENDS` | claude-only | JSON array of backends (alternative to the TOML file) |
| `KESTREL_DEFAULT_SESSION_BACKEND` | `claude` | Backend id used for ad-hoc `/api/sessions` dispatch |
| `KESTREL_STEP_BACKENDS` | `{}` | JSON map of workflow step → backend id |
| `KESTREL_VERSION` | `0.0.0-dev` | The running image's version. Baked in at build time; reported by `GET /healthz` |

`KESTREL_BACKENDS_FILE`, when set, supersedes `KESTREL_BACKENDS`,
`KESTREL_STEP_BACKENDS`, and `KESTREL_DEFAULT_SESSION_BACKEND`.

Unknown or stale `KESTREL_*` keys are ignored rather than causing a startup
failure, so a leftover key from a rename never crashes the service.

## Config files

- **`backend/.env`** — read only when running from source. Copy
  `backend/.env.example` and fill it in. It is gitignored; never commit it.
- **`backends.toml`** — the backend config pointed at by
  `KESTREL_BACKENDS_FILE`. Copy `backends.toml.example`. In Docker, mount it
  and set the env var (see [Backends](backends.md)). Read once at startup —
  restart after editing.

## The container image defaults

The image sets these so they normally need no changes:

| Variable | Image value |
| --- | --- |
| `KESTREL_STATIC_DIR` | `/app/static` (the baked-in SPA) |
| `KESTREL_DATABASE_URL` | `sqlite:////data/kestrel.db` |
| `KESTREL_WORKSPACE_ROOT` | `/workspaces` |
| `HOME` | `/data/home` (the writable, seeded Claude `HOME`) |
| `CLAUDE_SEED_DIR` | `/seed` (where host `~/.claude*` are mounted read-only) |

## Mounts

See [Getting started → Volumes](getting-started.md#volumes) for the full
mount table and how the host Claude config is seeded into the container.

## Health and version

`GET /healthz` returns `{"status":"ok","version":"…"}` when the service is
ready, and HTTP 503 if the database is unreachable. The container and compose
healthchecks use this endpoint. Use the `version` field to confirm which
image build is running.

## Secrets

The only secret kestrel itself consumes is `KESTREL_GITHUB_TOKEN` (optional).
Claude credentials come from your seeded host login, not from a kestrel
setting. Backend secrets (a secured opencode password, an LLM API key) live
in the backend config — see [Backends](backends.md).
