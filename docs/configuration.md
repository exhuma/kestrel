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
| `KESTREL_API_TOKEN` | _(empty)_ | Shared-secret bearer token gating `/api`. Empty ⇒ open API, loopback-bind only. See [Security](security.md) |
| `KESTREL_ALLOW_INSECURE_BIND` | _(empty)_ | Set to `1` to allow a non-loopback bind without an API token (container published to loopback only). See [Security](security.md) |
| `KESTREL_SENTINEL_SECRET` | _(empty)_ | HMAC key signing the "already refined" issue marker. Empty ⇒ markers are never trusted (always re-refine). See [Security](security.md) |
| `KESTREL_GITHUB_TOKEN` | _(empty)_ | Token for GitHub ingestion (issues, clone/push, PRs). See [GitHub workflow](setup-github-workflow.md) |
| `KESTREL_GITHUB_API_BASE` | `https://api.github.com` | GitHub REST API base URL (override for GitHub Enterprise) |
| `KESTREL_GIT_BASE` | `https://github.com` | Base URL for git clones |
| `KESTREL_ANTHROPIC_API_BASE` | `https://api.anthropic.com` | Anthropic API base; its host seeds the egress allowlist. See [Security](security.md) |
| `KESTREL_EGRESS_PROXY_URL` | _(empty)_ | Forward-proxy URL for the default-deny egress design. See [Security](security.md) |
| `KESTREL_EGRESS_ALLOWLIST` | `[]` | Extra hostnames to allow through egress (JSON list), beyond those derived from config |
| `KESTREL_DATABASE_URL` | `sqlite:///./kestrel.db` | SQLAlchemy database URL (image: `sqlite:////data/kestrel.db`) |
| `KESTREL_BACKENDS_FILE` | _(empty)_ | Path to a TOML backend config — the way to add backends. See [Backends](backends.md) |
| `KESTREL_LOG_LEVEL` | `info` | Console log verbosity (`debug`, `info`, `warning`, …) |
| `KESTREL_LOG_FORMAT` | `text` | Console log format: `text` (human-readable) or `json`. See [Observability](observability.md) |

Backends are configured **only** through `KESTREL_BACKENDS_FILE` (or the
`backends.toml` it points at) — see [Backends](backends.md).

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

## Logging

Logs go to stdout. `KESTREL_LOG_FORMAT` selects human-readable `text`
(default) or `json` (one JSON document per line) for a log pipeline, and
`KESTREL_LOG_LEVEL` sets verbosity. See [Observability](observability.md).

## Health and version

`GET /healthz` returns `{"status":"ok","version":"…"}` when the service is
ready, and HTTP 503 if the database is unreachable. The container and compose
healthchecks use this endpoint. Use the `version` field to confirm which
image build is running.

The version is baked into the image at build time (`KESTREL_VERSION`), so it
is not a setting you configure — it simply reports the running build.

## Secrets

The secrets kestrel itself consumes are `KESTREL_GITHUB_TOKEN` (optional) and
`KESTREL_API_TOKEN` (the API access gate). Kestrel runs an agent over
untrusted GitHub-issue text — read [Security](security.md) before deploying.
Claude credentials come from your seeded host login, not from a kestrel
setting. Backend secrets (a secured opencode password, an LLM API key) live
in the backend config — see [Backends](backends.md).
