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
| `KESTREL_HOST` | `0.0.0.0` | Uvicorn bind address for `python -m app`. The image keeps `0.0.0.0` so published compose ports work; behind a sidecar proxy set `127.0.0.1` (see [Kubernetes](deploy-kubernetes.md)) |
| `KESTREL_PORT` | `8000` | Uvicorn bind port for `python -m app` |
| `KESTREL_RELOAD` | `false` | Enable uvicorn dev auto-reload (`python -m app`) |
| `KESTREL_CLAUDE_BIN` | `claude` | Path/name of the `claude` CLI to spawn |
| `KESTREL_WORKSPACE_ROOT` | `./.kestrel-workspaces` | Where per-session git workspaces are created (image: `/workspaces`) |
| `KESTREL_PERMISSION_MODE` | `acceptEdits` | Passed to `claude --permission-mode` for spawned sessions |
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
| `KESTREL_PUBLIC_BASE_URL` | _(empty)_ | Public URL of the kestrel UI, used to build the link that ends every comment kestrel posts on a ticket (and its interview-form link). Empty ⇒ link-less comments |
| `KESTREL_POLL_INTERVAL_SECONDS` | `300` | How often every task source is re-checked (GitHub reconcile + Jira poll) |
| `KESTREL_SPECIALISTS_ROOT` | `./specialists` | Root of file-backed specialist role definitions for the work board (feature 026). Treated as a trust boundary — a manifest resolving outside this root is refused |
| `KESTREL_BOARD_INPUT_MAX_BYTES` | `65536` | Maximum size of one untrusted board input (task body, feedback, gate answer, direct prompt) accepted before intake; oversized input is quarantined |
| `KESTREL_BOARD_INPUT_SECURITY_TIMEOUT_SECONDS` | `30.0` | Timeout for the input-security specialist's classification call; a timeout fails closed into quarantine. The liaison's reading of a ticket reply (feature 046) uses it too; a timeout there makes kestrel ask the person back |
| `KESTREL_BOARD_CLAIM_LEASE_SECONDS` | `600` | How long a card claim lease is held before it is considered abandoned |
| `KESTREL_BOARD_WORKSPACE_LEASE_SECONDS` | `1800` | How long a repository workspace-write lease is held before recovery may reclaim it |
| `KESTREL_BOARD_MAX_PARALLEL_READ_CARDS` | `4` | Maximum read-only board cards claimed and active at once |
| `KESTREL_BOARD_RECOVERY_INTERVAL_SECONDS` | `60.0` | How often the recovery sweep checks for expired claim leases |
| `KESTREL_BOARD_PROJECTION_RETRY_INTERVAL_SECONDS` | `120.0` | How often comments kestrel failed to post to a ticket are tried again. Each failed comment waits twice as long after every failed retry (up to 32 intervals) and is given up on, still visible in the projection ledger, after 8 retries. A comment is posted at most once |
| `KESTREL_BOARD_COMMENT_POLL_INTERVAL_SECONDS` | `60.0` | How often the comments on the Jira tickets of requests in progress are read for replies (feature 046). Nothing is read while `comment_sentinel_enabled` is off: kestrel could not tell its own comments from replies |
| `KESTREL_FEEDBACK_MARKER` | `@kestrel` | The plain-text marker (whole word, any case) a person puts in a ticket reply for kestrel to act on (feature 046). The reporter's reply decides the understanding and the PRD, the change owner's CAB-1 and CAB-2; anyone else is told they cannot |
| `KESTREL_BOARD_ARTIFACTS_ROOT` | `./.kestrel-board-artifacts` | Durable, content-addressed store for handoff-artifact bodies |
| `KESTREL_STATIC_DIR` | _(empty)_ | Directory of the built SPA to serve. Empty ⇒ API-only (the Vite dev server serves the UI). Image: `/app/static` |
| `KESTREL_COMMENT_SENTINEL_ENABLED` | `true` | Mark every comment kestrel posts with its ownership marker. Kestrel posts through the operator's account, so this marker is how it tells its own comments from replies; with it off, no ticket reply is read. How the marker looks is each source adapter's concern |
| `KESTREL_HEALTH_CHECK_INTERVAL_SECONDS` | `60` | How often each task source's health (reachable and authenticated) is re-checked in the background |
| `KESTREL_HEALTH_CHECK_TIMEOUT_SECONDS` | `10` | How long one source health check may take before it counts as unhealthy |
| `KESTREL_MAX_VERIFY_ITERATIONS` | `3` | Verification rounds one approved coding task gets before it escalates to coordinator review |
| `KESTREL_MAX_CI_REPAIR_ITERATIONS` | `2` | Repair attempts after a failing required CI check on a delivered change request, independent of the verify rounds |
| `KESTREL_BOARD_TURN_TIMEOUT_SECONDS` | `600.0` | Timeout for one agent turn on the board (the coordinator's or a specialist's). Raise it for slow local models |
| `KESTREL_BOARD_CI_POLL_INTERVAL_SECONDS` | `60.0` | How often the CI sweep checks delivered workflows' required CI status. A no-op without `required_ci_statuses` on the source |
| `KESTREL_BOARD_UNREADABLE_RETRY_CAP` | `1` | How often a card whose result cannot be read is retried before it escalates to the coordinator. `0` escalates at once |
| `KESTREL_BOARD_CAB1_INTERVIEW_MAX_QUESTIONS` | `3` | Hard cap on the questions of the strategic-fit interview before CAB-1 |
| `KESTREL_BOARD_REFINEMENT_ROUND_CAP` | `1` | Refinement-interview rounds per persona; above `1`, a persona whose answers stay ambiguous gets another round |
| `KESTREL_BOARD_PRD_REDRAFT_CAP` | `1` | PRD redrafts per workflow after a PRD gate rejection; a further rejection escalates to the operator |
| `KESTREL_BOARD_UNDERSTANDING_REDRAFT_CAP` | `2` | Redrafts of the restated understanding after a rejection; a further rejection opens a coordinator review. `0` never redrafts |
| `KESTREL_BOARD_DEV_ACTIONS_ENABLED` | `false` | Temporary dev-only cleanup/rerun routes, restricted to private (local-task) workflows. Leave off in a real deployment |

**Vestigial settings, not currently read by anything.** A handful of
`Settings` fields survive from the deleted fixed driver purely because
nobody has removed them yet from `backend/app/config.py`: `workflow_debug`,
`refine_samples`, `refine_critic`, `reconcile_mode`,
`allow_incomplete_answers`, and `mockups_enabled`. Setting their
`KESTREL_*` env var or `config.toml` key is accepted at startup but has
**no effect** — nothing in the codebase reads any of them outside
`config.py` itself. They described the old driver's debug transcript and
refine-interview robustness knobs, none of which exist post-Phase-10; do
not rely on any of them. (This is a known cleanup gap, tracked separately.)
Ticket replies marked with `@kestrel` do exist again since feature 046; they
use `feedback_marker`, which is a live setting listed above.

**Task sources are configured in `config.toml`, not via env vars.** Which
GitHub repos and Jira instances kestrel pulls from — the former
`KESTREL_WATCHED_REPOS`, `KESTREL_TRIGGER_LABEL`, `KESTREL_JIRA_*`, and
`KESTREL_CODE_HOST*` keys — are now a file-only `[[task_sources]]` list (see
[Task sources](#task-sources) below). Those env keys have been removed and are
ignored if left over.

Only some settings may be set in `config.toml` (the file wins where it sets
one; the environment fills in the rest). Any other key in the file is
ignored. The file-overridable keys are: `poll_interval_seconds`,
`max_verify_iterations`, `max_ci_repair_iterations`, `port`, `database_url`,
`workspace_root`, `board_artifacts_root`, `comment_sentinel_enabled`,
`feedback_marker`, `specialists_root`, `board_input_max_bytes`,
`board_input_security_timeout_seconds`, `board_turn_timeout_seconds`,
`board_claim_lease_seconds`, `board_workspace_lease_seconds`,
`board_max_parallel_read_cards`, `board_recovery_interval_seconds`,
`board_ci_poll_interval_seconds`, `board_comment_poll_interval_seconds`,
`board_projection_retry_interval_seconds`,
`board_cab1_interview_max_questions`, `board_unreadable_retry_cap`,
`health_check_interval_seconds`, `health_check_timeout_seconds`, and
`board_dev_actions_enabled`. Everything else (for example `KESTREL_HOST`,
`KESTREL_PUBLIC_BASE_URL`, `KESTREL_LOG_*`, the redraft and refinement caps)
is environment-only. Secrets have no TOML equivalent, except a backend's
inline `password`/`api_key`.

## Task sources

Each origin kestrel pulls work from is one entry in the **file-only**
`[[task_sources]]` list in `config.toml`. An entry declares its `type` and that
source's selection criteria; **tokens stay in the environment** — an entry names
the env var holding its token via `token_env` (defaulting per type), so the file
stays secret-free. Add more entries (including two of the same type) as needed.

```toml
poll_interval_seconds = 300            # one cadence for every source
health_check_interval_seconds = 60     # how often source health is re-checked
health_check_timeout_seconds = 10      # per-check timeout before giving up

[[task_sources]]
type = "github"
watched_repos = ["owner/name"]         # ingest/reconcile allow-list
trigger_label = "kestrel"              # issue label that triggers ingestion
# token_env = "KESTREL_GITHUB_TOKEN"   # optional (default)

[[task_sources]]
type = "jira"
base_url = "https://acme.atlassian.net"
deployment = "cloud"                   # cloud (ADF/v3) | server (text/v2, the default)
auth = "basic"                         # basic (Cloud) | bearer (Server/DC PAT)
email = "me@acme.com"
jql = 'project = "RFC" AND status = "Ready"'  # one whole query, you write it
key = "RFC"                            # issue-key prefix; scopes dismissals only
verify_ssl = true                      # false ⇒ skip TLS checks on REST/API calls
# token_env = "KESTREL_JIRA_API_TOKEN" # optional (default)
repo_field = "customfield_10050"       # optional; else a titled web link is used
repo_link_text = "Repository"          # web-link title to match (default)
change_owner_field = ""                # optional; Jira user field naming the change owner
code_host = "github"                   # github | gitlab | gitea (self-hostable)
code_host_base_url = ""                # for a self-hosted gitlab/gitea
# code_host_token_env = "KESTREL_CODE_HOST_TOKEN"

[[task_sources]]
type = "local"
tasks_dir = "/path/to/kestrel-local-tasks"  # required task-folder root
code_host = "local"                    # required; no credential
```

A `local` source runs disposable task folders, each with `task.json`, under
`tasks_dir`. It uses an absolute local bare repository path from the
task's `code_repo`, publishes a branch there, and never opens a change
request. See [Local tasks workflow](setup-local-tasks.md) for the task file
format. (The fixed driver's **Rerun** action — abandon a run, delete its
branch, restart it against the same task — was removed with that driver in
the Phase 10 clean break and has no board-domain replacement yet; see
[Architecture](architecture.md#the-work-board-spec-026).)

### Translation

`config.toml` may declare a separate OpenAI-compatible translation service
(shown below), but nothing in the current board domain calls it — it was
wired to the deleted feedback-intake subsystem and has no board-domain
caller yet. Declaring it is a no-op for now.

```toml
[translation]
base_url = "https://translation.example.com/v1"
model = "translation-model"
api_key_env = "KESTREL_TRANSLATION_API_KEY"
# timeout = 30.0
```

### Decomposed tasks and verification rounds

An approved decomposition (CAB-2) does **not** create tickets in the task
source. Its tasks become cards inside the request's own workflow, and the
request's ticket gets one comment listing them (feature 031). There is
nothing to configure for this. The former `child_task_closure_retention_days`
setting has been removed; an existing `config.toml` that still sets it loads
fine, because unknown keys are ignored.

`max_verify_iterations` (default 3) caps how many verification rounds one
approved coding task gets. A verification that still finds problems at the cap
escalates to coordinator review instead of asking the coder for another fix.
`max_ci_repair_iterations` (default 2) caps how many times a failing required CI
check on a delivered change request sends work back to the coder before it
escalates.

A Jira RFC's target repository is resolved from `repo_field` when set, otherwise
from a remote/web link on the issue whose title matches `repo_link_text`
("Repository" by default). Verify a source's configuration without starting runs
with `python -m app poll`, which lists the work items each configured source
currently matches. An RFC whose repository can't be resolved (missing
field/link, or the code host is unreachable) is logged, never commented
on the ticket — this fires every poll cycle for as long as it stays
unresolved, so a comment there would spam the RFC; check the
source-health indicator first if every RFC is suddenly unresolved, since
that usually means the code host itself is the problem, not any one
ticket.

Set `verify_ssl = false` on a source (github or jira) to skip TLS certificate
verification on its **REST/API** calls — for a self-hosted instance whose CA the
process does not trust. This covers the Jira and code-host HTTP clients (which
use their own bundled CA set, not the OS trust store). It does **not** affect
`git` clone/fetch/push, which use the system trust store — install the internal
CA there for git.

### Lifecycle sync and operator hooks (currently dormant)

Each source still accepts the fields below, and the `TaskSource.transition()`
methods and hook-invocation code they'd drive still exist, but **nothing in
the current board domain calls either** — the old driver code that invoked
them at each lifecycle point (start/done/failed/escalated/rejected) was
removed in the Phase 10 clean break and has no board-domain replacement yet
(see [Architecture](architecture.md#the-work-board-spec-026)). Setting these
fields today has no observable effect: no label is applied, no transition
fires, and no `hooks_dir` executable runs (only its startup audit-log pass
still does). They are documented here for when this is wired back up.

When it is, the constitution (access model, fourth recorded constraint)
limits it: kestrel never changes the status of an ingested task. The
transition ids may only move sub-tasks kestrel created itself; where the
ingested ticket should move on, kestrel asks its owner in a comment.

| Field | Source type | Purpose |
| --- | --- | --- |
| `in_progress_label`, `failed_label`, `escalated_label`, `rejected_label` | github | Issue labels a run would apply as it progresses. Default to `kestrel-in-progress`/`kestrel-failed`/`kestrel-escalated`/`kestrel-rejected` |
| `transition_start`, `transition_done`, `transition_failed`, `transition_escalated`, `transition_rejected` | jira | Workflow-transition ids that would apply at each point. Unset ⇒ no-op for that point, not an error — every Jira workflow is different |
| `time_spent_field` | jira | Field that would receive active-work seconds (e.g. the builtin `timespent` or a custom field id). Unset ⇒ no native write |
| `hooks_dir` | both | A directory of operator executables that would be invoked at every lifecycle event. **Security-sensitive** — a hook inherits kestrel's full environment/credentials. See [Operator hooks](hooks.md) before setting this |

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

Each `[[backends]]` entry can also set `max_concurrency` (positive integer,
default `1`) to cap all in-flight turns for that backend ID across every
workflow and ad-hoc session in the process. `opencode` entries additionally
support `rate_limit_retries` (non-negative integer, default `3`) and
`rate_limit_backoff_seconds` (positive number, default `2.0`) for HTTP 429
retries. See [Concurrency and rate limits](backends.md#concurrency-and-rate-limits).

Unknown or stale `KESTREL_*` keys are ignored rather than causing a startup
failure, so a leftover key from a rename never crashes the service.

## Config files

The recommended layout keeps the two kinds of settings apart:

- **`config.toml` — the preferred home for non-secret configuration.** The
  file-only `[[task_sources]]` list and backend routing, plus applicative
  overrides such as `poll_interval_seconds` and the `board_*` settings,
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
| `KESTREL_BOARD_ARTIFACTS_ROOT` | `/data/board-artifacts` (on the persisted `/data` volume) |
| `HOME` | `/data/home` (the writable, seeded Claude `HOME`) |
| `CLAUDE_SEED_DIR` | `/seed` (where host `~/.claude*` are mounted read-only) |

## Mounts

See [Getting started → Volumes](getting-started.md#volumes) for the full
mount table and how the host Claude config is seeded into the container.

## Running as a non-root user

The image runs as a baked-in `kestrel` user, **uid/gid `1000`** — not root.
This is standard Docker, not a kestrel-specific setting: override it at
container-start with the native `user:` field in `docker-compose.yml` (or
`docker run --user uid:gid`) to match a different host user, e.g. to share
`./workspaces` with a sidecar container (such as an opencode instance) that
needs to read/write the same files.

What's automatic vs. what the operator provisions:

- **`/data`** (the `kestrel-data` named volume) needs no action — a fresh
  named volume initializes from the image's `/data` directory, which is
  already owned by `kestrel:kestrel` at build time.
- **`/workspaces`** (and any other bind mount) is **not** pre-populated this
  way. It must already exist on the host, owned by the uid:gid the container
  runs as, *before* the first `docker compose up` — see
  [Getting started → Volumes](getting-started.md#volumes). The entrypoint
  fails fast with a clear error if it isn't writable; see
  [Troubleshooting](troubleshooting.md#mount-permission-errors-on-workspaces).

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

Secrets always stay in the environment (a Kubernetes Secret, a `.env`, the
compose `environment:` block). Kestrel consumes:

- `KESTREL_GITHUB_TOKEN`: GitHub ingestion, clone/push and pull requests
  (also the code-host token of a Jira source whose `code_host` is github);
- `KESTREL_WEBHOOK_SECRET`: verifies GitHub webhook deliveries (not needed for
  Jira, which is poll-only);
- `KESTREL_JIRA_API_TOKEN`, or the variable a source names in `token_env`;
- `KESTREL_CODE_HOST_TOKEN`, or the variable named in `code_host_token_env`;
- per-backend credentials named by a backend's `api_key_env` (for example
  the opencode server password) and the translation `api_key_env`.

Claude credentials come from your seeded host login, not from a kestrel
setting. See [Backends](backends.md) for backend secrets.
