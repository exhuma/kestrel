# Configuration

Kestrel is configured through `KESTREL_*` environment variables (or a
`backend/.env` file when running from source) and an optional `config.toml`
file. **Secrets always stay in the environment**; the TOML file holds backend
routing and applicative (non-secret) settings such as the watched-repo
allow-list and verify knobs. Where the file sets an applicative key it wins;
the environment fills in the rest. See [Backends](backends.md) for the backend
side.

## Environment variables

Every setting, with its default. Prefix is `KESTREL_`; the field name is the
lower-cased remainder (e.g. `KESTREL_GITHUB_TOKEN` → `github_token`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `KESTREL_HOST` | `0.0.0.0` | Uvicorn bind address for `python -m app` |
| `KESTREL_PORT` | `8000` | Uvicorn bind port for `python -m app` |
| `KESTREL_RELOAD` | `false` | Enable uvicorn dev auto-reload (`python -m app`) |
| `KESTREL_CLAUDE_BIN` | `claude` | Path/name of the `claude` CLI to spawn |
| `KESTREL_WORKSPACE_ROOT` | `./.kestrel-workspaces` | Where per-session git workspaces are created (image: `/workspaces`) |
| `KESTREL_PERMISSION_MODE` | `acceptEdits` | Passed to `claude --permission-mode` for spawned sessions |
| `KESTREL_MODEL_OVERRIDES` | `{}` | JSON map of per-step model overrides, e.g. `{"sonnet":"claude-sonnet-5"}` |
| `KESTREL_GITHUB_TOKEN` | _(empty)_ | Token for GitHub ingestion (issues, clone/push, PRs). See [GitHub workflow](setup-github-workflow.md) |
| `KESTREL_GITHUB_API_BASE` | `https://api.github.com` | GitHub REST API base URL (override for GitHub Enterprise) |
| `KESTREL_GIT_BASE` | `https://github.com` | Base URL for git clones |
| `KESTREL_DATABASE_URL` | `sqlite:///./kestrel.db` | SQLAlchemy database URL (image: `sqlite:////data/kestrel.db`) |
| `KESTREL_CONFIG_FILE` | _(empty)_ | Path to the TOML config file (backend routing + applicative overrides). See [Backends](backends.md). `KESTREL_BACKENDS_FILE` is a deprecated alias |
| `KESTREL_LOG_LEVEL` | `info` | Console log verbosity (`debug`, `info`, `warning`, …) |
| `KESTREL_LOG_FORMAT` | `text` | Console log format: `text` (human-readable) or `json`. See [Observability](observability.md) |
| `KESTREL_OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing. When true, also set the `OTEL_*` vars below. See [Observability → Tracing](observability.md#tracing) |
| `KESTREL_OTEL_SERVICE_NAME` | `kestrel` | `service.name` reported on exported spans |
| `KESTREL_WEBHOOK_SECRET` | _(empty)_ | HMAC shared secret verifying GitHub webhook deliveries. Empty disables the webhook path. Never logged. See [GitHub workflow](setup-github-workflow.md) |
| `KESTREL_WATCHED_REPOS` | _(empty)_ | Allow-list of `owner/name` repos to ingest/reconcile. Comma-separated or a JSON array. Anything outside is ignored |
| `KESTREL_TRIGGER_LABEL` | `kestrel` | Issue label that flags an issue for ingestion |
| `KESTREL_RECONCILE_INTERVAL_SECONDS` | `300` | How often reconciliation polls watched repos for missed deliveries |
| `KESTREL_PUBLIC_BASE_URL` | _(empty)_ | Public URL of the kestrel UI, used to build clickable gate-notification deep-links. Empty ⇒ link-less comments |
| `KESTREL_JIRA_BASE_URL` | _(empty)_ | Jira instance base URL. Empty disables Jira polling. Poll-only — no inbound endpoint. See [Jira workflow](setup-jira-workflow.md) |
| `KESTREL_JIRA_AUTH` | `basic` | `basic` (Cloud: email + API token) or `bearer` (Server/DC: PAT) |
| `KESTREL_JIRA_EMAIL` | _(empty)_ | Basic-auth username (Jira Cloud email) |
| `KESTREL_JIRA_API_TOKEN` | _(empty)_ | Jira API token / PAT. Secret; never logged |
| `KESTREL_JIRA_PROJECT` | _(empty)_ | RFC project key polled for change requests (required to poll) |
| `KESTREL_JIRA_JQL_FILTER` | _(empty)_ | Extra JQL AND-ed onto `project = "<key>"`, e.g. `status = "Ready"` |
| `KESTREL_JIRA_REPO_FIELD` | _(empty)_ | RFC field id/name holding the target `owner/name[@base_branch]` |
| `KESTREL_JIRA_POLL_INTERVAL_SECONDS` | `300` | How often the Jira project is polled for qualifying RFCs |
| `KESTREL_CODE_HOST` | `github` | Code host for Jira-resolved repos: `github`, `gitlab`, or `gitea` (self-hostable) |
| `KESTREL_CODE_HOST_BASE_URL` | _(empty)_ | Self-hosted code-host instance URL (e.g. `https://gitlab.internal`) |
| `KESTREL_CODE_HOST_TOKEN` | _(empty)_ | Code-host token/PAT. Secret; never logged. Falls back to `KESTREL_GITHUB_TOKEN` when `code_host=github` |
| `KESTREL_VERIFY_CHECKS` | `[]` | JSON list of shell commands run in the worktree as verify evidence, e.g. `["uv run pytest -q"]`. Empty ⇒ model-judgment fallback |
| `KESTREL_MAX_VERIFY_ITERATIONS` | `3` | Max code↔verify rounds before the loop escalates to the ticket |

The applicative keys `KESTREL_WATCHED_REPOS`, `KESTREL_TRIGGER_LABEL`,
`KESTREL_RECONCILE_INTERVAL_SECONDS`, `KESTREL_VERIFY_CHECKS`, and
`KESTREL_MAX_VERIFY_ITERATIONS` can also be set in `config.toml` (as
`watched_repos`, `trigger_label`, …). The file wins where it sets a key; the
environment fills in the rest. Secrets have no TOML equivalent.

### Tracing (`OTEL_*`, only when `KESTREL_OTEL_ENABLED=true`)

Tracing reads the **standard** OpenTelemetry environment variables — kestrel
does not rename them under `KESTREL_`:

| Variable | Example | Purpose |
| --- | --- | --- |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://collector:4318` | OTLP/HTTP collector endpoint for span export |
| `OTEL_TRACES_SAMPLER_ARG` | `1.0` | Head sampling ratio (parent-based); `1.0` = sample all |

See [Observability → Tracing](observability.md#tracing) for the full model.

Backends are configured **only** through `KESTREL_CONFIG_FILE` (or the
`config.toml` it points at) — see [Backends](backends.md).

Unknown or stale `KESTREL_*` keys are ignored rather than causing a startup
failure, so a leftover key from a rename never crashes the service.

## Config files

The recommended layout keeps the two kinds of settings apart:

- **`config.toml` — the preferred home for non-secret configuration.** Backend
  routing plus the applicative overrides (`watched_repos`, `trigger_label`,
  `reconcile_interval_seconds`, `verify_checks`, `max_verify_iterations`),
  pointed at by `KESTREL_CONFIG_FILE`. Copy `config.toml.example`. In Docker,
  mount it and set the env var (see [Backends](backends.md)). Read once at
  startup — restart after editing. (`KESTREL_BACKENDS_FILE` still works as a
  deprecated alias.)
- **`backend/.env` — secrets and the not-yet-migrated env-only settings.** Read
  only when running from source. Copy `backend/.env.example` and fill it in; it
  is gitignored, so never commit it. The example leads with `config.toml` and
  comments out the settings that now belong there — put your tokens
  (`KESTREL_GITHUB_TOKEN`, `KESTREL_WEBHOOK_SECRET`, `KESTREL_JIRA_API_TOKEN`,
  `KESTREL_CODE_HOST_TOKEN`) here and prefer the TOML file for everything else.

Any applicative key set in both places is taken from `config.toml`; the
environment only fills in what the file omits.

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
