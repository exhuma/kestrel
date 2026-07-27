# Configuration

Kestrel is configured through `KESTREL_*` environment variables (or a
`backend/.env` file when running from source) and an optional `config.toml`
file. **Secrets always stay in the environment**; the TOML file holds backend
routing and applicative (non-secret) settings such as the watched-repo
allow-list and the verify iteration cap. Where the file sets an applicative
key it wins; the environment fills in the rest. See [Backends](backends.md)
for the backend side.

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
| `KESTREL_JIRA_API_TOKEN` | _(empty)_ | Default token env var for a `jira` task source. Secret; never logged |
| `KESTREL_CODE_HOST_TOKEN` | _(empty)_ | Default code-host token for a Jira source's resolved repos. Secret; falls back to `KESTREL_GITHUB_TOKEN` when its `code_host` is github |
| `KESTREL_PUBLIC_BASE_URL` | _(empty)_ | Public URL of the kestrel UI, used to build clickable gate-notification deep-links. Empty ⇒ link-less comments |
| `KESTREL_POLL_INTERVAL_SECONDS` | `300` | How often every task source is re-checked (GitHub reconcile + Jira poll) |
| `KESTREL_MAX_VERIFY_ITERATIONS` | `3` | Max code↔verify rounds before the loop escalates to the ticket |
| `KESTREL_WORKFLOW_DEBUG` | `false` | Debug the code↔verify dialogue: appends every coder/verifier prompt and result to `<workspace>-debug/dialogue.log` and skips auto-deleting the worktree (done/escalated/failed) so both stay inspectable. An explicit abandon still deletes the workspace |
| `KESTREL_REFINE_SAMPLES` | `1` | Run the refine coordinator/generators N times and union the result, to reduce variance on weaker/local models |
| `KESTREL_REFINE_CRITIC` | `false` | Add an adversarial completeness pass after refine's reconciliation step |
| `KESTREL_RECONCILE_MODE` | `rewrite` | How refine consolidates overlapping questions: `rewrite` (LLM rewriter), `dedup` (no-LLM, coverage-safe within-audience dedup), or `off` (keep the pooled questions as-is) |
| `KESTREL_ALLOW_INCOMPLETE_ANSWERS` | `false` | Safety net: let a questionnaire be submitted with required questions left blank. Provided answers are still validated for well-formedness |

A project's user-facing boundary (HTTP API, web UI, both, or none) is inferred
by the `design` step from the PRD and codebase, not configured — there is no
`KESTREL_*` setting for it. When a boundary is found, `verify` launches and
exercises the running project for real using whatever tools (Bash, MCP) the
configured backend already has available — this is verify's only evidence
source; durable, deterministic checks (tests, lint) are the coder's TDD
responsibility, not something kestrel re-runs during verify.

**Task sources are configured in `config.toml`, not via env vars.** Which
GitHub repos and Jira instances kestrel pulls from — the former
`KESTREL_WATCHED_REPOS`, `KESTREL_TRIGGER_LABEL`, `KESTREL_JIRA_*`, and
`KESTREL_CODE_HOST*` keys — are now a file-only `[[task_sources]]` list (see
[Task sources](#task-sources) below). Those env keys have been removed and are
ignored if left over.

The applicative keys `KESTREL_POLL_INTERVAL_SECONDS` and
`KESTREL_MAX_VERIFY_ITERATIONS` can also be set in `config.toml` (as
`poll_interval_seconds`, …). The file wins where it sets a key; the environment
fills in the rest. Secrets have no TOML equivalent.

## Task sources

Each origin kestrel pulls work from is one entry in the **file-only**
`[[task_sources]]` list in `config.toml`. An entry declares its `type` and that
source's selection criteria; **tokens stay in the environment** — an entry names
the env var holding its token via `token_env` (defaulting per type), so the file
stays secret-free. Add more entries (including two of the same type) as needed.

```toml
poll_interval_seconds = 300            # one cadence for every source

[[task_sources]]
type = "github"
watched_repos = ["owner/name"]         # ingest/reconcile allow-list
trigger_label = "kestrel"              # issue label that triggers ingestion
# token_env = "KESTREL_GITHUB_TOKEN"   # optional (default)

[[task_sources]]
type = "jira"
base_url = "https://acme.atlassian.net"
auth = "basic"                         # basic (Cloud) | bearer (Server/DC PAT)
email = "me@acme.com"
jql = 'project = "RFC" AND status = "Ready"'  # one whole query, you write it
key = "RFC"                            # issue-key prefix; scopes dismissals only
verify_ssl = true                      # false ⇒ skip TLS checks on REST/API calls
# token_env = "KESTREL_JIRA_API_TOKEN" # optional (default)
repo_field = "customfield_10050"       # optional; else a titled web link is used
repo_link_text = "Repository"          # web-link title to match (default)
code_host = "github"                   # github | gitlab | gitea (self-hostable)
code_host_base_url = ""                # for a self-hosted gitlab/gitea
# code_host_token_env = "KESTREL_CODE_HOST_TOKEN"
```

A Jira RFC's target repository is resolved from `repo_field` when set, otherwise
from a remote/web link on the issue whose title matches `repo_link_text`
("Repository" by default). Verify a source's configuration without starting runs
with `python -m app poll`, which lists the work items each configured source
currently matches.

Set `verify_ssl = false` on a source (github or jira) to skip TLS certificate
verification on its **REST/API** calls — for a self-hosted instance whose CA the
process does not trust. This covers the Jira and code-host HTTP clients (which
use their own bundled CA set, not the OS trust store). It does **not** affect
`git` clone/fetch/push, which use the system trust store — install the internal
CA there for git.

### Lifecycle sync and operator hooks

Each source also carries fields governing how kestrel reports a run's
status ("in progress" / "done" / a failure terminal) and its active/wait
time back to the ticket, and an optional escape hatch for anything kestrel
doesn't natively support:

| Field | Source type | Purpose |
| --- | --- | --- |
| `in_progress_label`, `failed_label`, `escalated_label`, `rejected_label` | github | Issue labels applied as a run progresses. Default to `kestrel-in-progress`/`kestrel-failed`/`kestrel-escalated`/`kestrel-rejected` |
| `transition_start`, `transition_done`, `transition_failed`, `transition_escalated`, `transition_rejected` | jira | Workflow-transition ids applied at each point. Unset ⇒ no-op for that point, not an error — every Jira workflow is different |
| `time_spent_field` | jira | Field to write active-work seconds to (e.g. the builtin `timespent` or a custom field id). Unset ⇒ no native write |
| `hooks_dir` | both | A directory of operator executables invoked at every lifecycle event. **Security-sensitive** — a hook inherits kestrel's full environment/credentials. See [Operator hooks](hooks.md) before setting this |

Wherever a field above doesn't apply (the platform has no such mechanism,
none is configured, or the native call itself fails), kestrel falls back to
a footer appended to the comment it already posts — the operator always
sees the status/time information somewhere, on every platform.

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

- **`config.toml` — the preferred home for non-secret configuration.** The
  file-only `[[task_sources]]` list and backend routing, plus the applicative
  overrides (`poll_interval_seconds`, `max_verify_iterations`),
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

When kestrel is started as `python -m app`, `backend/.env` is loaded into the
process environment at startup. This matters for the **named token env vars** a
task source references (`token_env` / `code_host_token_env`) and the standard
`OTEL_*` vars: those are resolved from the environment, so a secret placed only
in `.env` is picked up too (real environment values still win over `.env`).

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
