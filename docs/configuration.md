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
| `KESTREL_BACKENDS_FILE` | _(empty)_ | Path to a TOML backend config — the way to add backends. See [Backends](backends.md) |
| `KESTREL_LOG_LEVEL` | `info` | Console log verbosity (`debug`, `info`, `warning`, …) |
| `KESTREL_LOG_FORMAT` | `text` | Console log format: `text` (human-readable) or `json`. See [Observability](observability.md) |
| `KESTREL_OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing. When true, also set the `OTEL_*` vars below. See [Observability → Tracing](observability.md#tracing) |
| `KESTREL_OTEL_SERVICE_NAME` | `kestrel` | `service.name` reported on exported spans |

### Tracing (`OTEL_*`, only when `KESTREL_OTEL_ENABLED=true`)

Tracing reads the **standard** OpenTelemetry environment variables — kestrel
does not rename them under `KESTREL_`:

| Variable | Example | Purpose |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://collector:4318` | OTLP/HTTP collector endpoint for span export |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Head sampling ratio (parent-based); `1.0` = sample all |

See [Observability → Tracing](observability.md#tracing) for the full model.

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

Kestrel exposes `GET /livez`, `GET /readyz`, and `GET /healthz`. Each returns
a compact JSON body (`probe`, `status`, `checked_at`, `components`) with HTTP
200 when healthy and 503 when a required dependency fails. The container and
compose healthchecks call `/readyz`. See
[Observability → Health](observability.md#health) for the full contract.

The running build is reported in the `X-Kestrel-Version` response header (not
the body — health payloads must not leak version fingerprints):

```bash
curl -sD - -o /dev/null http://localhost:8000/livez | grep -i x-kestrel-version
```

The version is baked into the image at build time (`KESTREL_VERSION`); it is
read-only and simply reports the running build.

## Secrets

The only secret kestrel itself consumes is `KESTREL_GITHUB_TOKEN` (optional).
Claude credentials come from your seeded host login, not from a kestrel
setting. Backend secrets (a secured opencode password, an LLM API key) live
in the backend config — see [Backends](backends.md).
