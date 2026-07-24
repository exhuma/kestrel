# Phase 0 Research: Task-source configuration abstraction & poll tooling

All Technical Context items were known from the existing codebase (features 002
and 003) and the approved implementation plan; no external NEEDS CLARIFICATION
remained. This document records the design decisions that resolve the spec's
requirements into an implementable shape.

## D1 — Configuration model: one `TaskSourceConfig`, discriminated by `type`

**Decision**: Add a single pydantic `TaskSourceConfig` model (mirroring the
existing `BackendConfig`) with a `type: Literal["github", "jira"]` discriminator
and per-type optional fields, plus a model validator that enforces the
required fields for each type. Add `task_sources: list[TaskSourceConfig]` to
`Settings`, resolved **file-only** (added to `_FILE_ONLY_FIELDS` and built in
`_apply_config_file`, exactly like `backends`).

**Rationale**: `BackendConfig` already proves this shape passes the quality
gate and the file-only overlay mechanism. A single model with a discriminator
keeps one class and one validator rather than a union of models plus custom
parsing (fewer symbols, lower complexity). File-only is correct because the list
is structured (arrays/tables don't map cleanly to flat `KESTREL_*` env vars) and
matches `backends`.

**Alternatives considered**: (a) A discriminated union of `GitHubSourceConfig` /
`JiraSourceConfig` — cleaner typing but more classes and pydantic-union parsing
complexity for a two-type set; revisit if a third type makes the single model
unwieldy. (b) Keeping env-var support for the list — rejected; structured lists
belong in the file, consistent with `backends`.

## D2 — Secrets: `token_env` naming, resolved like `BackendConfig.secret()`

**Decision**: Each source entry carries `token_env` — the **name** of the
environment variable holding its token — and a `.token()` method returning
`os.environ.get(self.token_env)`. Sensible per-type defaults
(`KESTREL_GITHUB_TOKEN` for github, `KESTREL_JIRA_API_TOKEN` for jira, and the
code-host token env for the Jira entry's code host) keep existing setups working.

**Rationale**: This is the established `api_key_env` pattern from `BackendConfig`
and honours Constitution V (".env stays out of VCS"; the TOML file is
secret-free). It also naturally supports two sources needing two different
tokens.

**Alternatives considered**: Inline token in the TOML (as `BackendConfig`
tolerates for a gitignored file) — rejected as the default because ingestion
tokens are higher-value and the file is meant to be secret-free; not offered.

## D3 — Per-source code-host config lives on the Jira entry

**Decision**: The Jira entry carries its repository-resolution + code-host
settings: `repo_field` (optional), `repo_link_text` (default "Repository"),
`code_host` (`github`|`gitlab`|`gitea`), `code_host_base_url`, and
`code_host_token_env`. The top-level `code_host*` scalars are removed.

**Rationale**: The resolved-repo code host is a property *of a Jira source*.
Putting it on the entry keeps each source self-describing and lets future Jira
sources target different hosts — the whole point of the abstraction. A global
scalar would re-introduce the source-specific top-level key this feature removes.
Recorded in the plan's Complexity Tracking.

**Alternatives considered**: One global `code_host` — simpler but breaks with two
Jira sources on different hosts and contradicts the abstraction; rejected.

## D4 — Multiple entries per type: one poll loop per configured source

**Decision**: Introduce `configured_poll_sources(settings) -> list[PollSource]`
(in `services/poll_source.py`). It yields one `PollSource` per configured entry:
a reconcile-backed source per `github` entry and a jira-poll-backed source per
`jira` entry. `ReconcileService` and `JiraPollService` are each parameterized by
**one** source config (repos+label, or base_url+jql+client) rather than reading
global scalars. The lifespan starts one `run_forever` task per `PollSource`; the
CLI iterates the same list.

**Rationale**: A list inherently allows N entries; binding each service instance
to one source config makes that fall out naturally, removes the global-scalar
reads, and unifies the lifespan gating (today duplicated twice) behind one
iterator. Dismissal-clearing stays per-source (each service clears only its own
source's refs), preserving 002/003 behaviour. Because `jira_project` is removed,
each Jira entry carries an explicit `key` (the issue-key prefix, e.g. `RFC`) used
**only** to scope its dismissal-clear (`f"{entry.key}-"`), replacing the former
`f"{jira_project}-"` prefix — selection is governed solely by the whole `jql`.
(Chosen over parsing the key out of the JQL, which is brittle, and over tracking
emitted refs, which adds persistent state.)

**Alternatives considered**: One service reading the whole list internally —
concentrates multi-source looping inside each service and keeps a
service↔settings coupling; the per-source instance is cleaner and smaller per
function.

## D5 — Non-ingesting listing reuses the live query (no divergence)

**Decision**: Extract the query half of each `run_cycle` into a reused method —
`ReconcileService._list_labelled(repo)` and `JiraPollService._search_tasks()` —
called by both `run_cycle` (which then ingests) and a new
`list_work_items() -> list[WorkItem]` (which resolves the repo but never calls
`maybe_start_run`). `WorkItem` is a small dataclass (`source`, `ref`, `title`,
`code_repo | None`, `base_branch | None`).

**Rationale**: FR-012 requires the dry-run and the live poll to use the same
selection logic. Extracting the shared query method guarantees it and keeps each
function within the quality limits (jscpd stays low — the query lives in one
place).

## D6 — Jira repo resolution: field first, then title-matched web link

**Decision**: `JiraClient.get_remote_links(key)` calls
`GET /rest/api/2/issue/{key}/remotelink` and returns the raw list. A module-level
pure `_repo_from_url(url)` parses `owner/name` from a hosted URL via
`urllib.parse.urlparse().path` (trimming a trailing `.git`; for GitLab
deep-links, truncating at the `/-/` marker). `_resolve_repo` is split into small
helpers: `_repo_ref` (field when configured, else `_repo_ref_from_links`),
`_repo_ref_from_links` (fetch links, case-insensitively match the entry's
`repo_link_text`, parse the URL), `_split_repo_ref` (`owner/name[@base]`), and
`_probe` (default-branch reachability check). The custom field becomes optional.

**Rationale**: Splitting keeps every helper well under the complexity/return/
branch ceilings while adding the fallback. `urllib.parse` is stdlib (no new
dependency). Field-first preserves existing behaviour (FR-013).

**Alternatives considered**: Regex URL parsing — more brittle across hosts than
path-splitting; rejected. Scanning the issue description body for URLs — out of
scope (not requested); rejected.

## D7 — CLI: `argparse` dispatch, thin `__main__`, bodies in `app/cli.py`

**Decision**: `app/cli.py` holds `build_parser()` (subparsers `serve` [default
via `set_defaults`] and `poll`), `cmd_serve(settings)` (the uvicorn launch,
reading `settings.host/port/reload` from change set A), `cmd_poll(settings)` →
`asyncio.run(_run_poll(settings))`, `_run_poll` (iterate
`configured_poll_sources`, `await list_work_items`, hand to `_print_items`),
`_print_items(name, items)`, and `main(argv=None) -> int`. `__main__.py` becomes
`from app.cli import main; raise SystemExit(main())`.

**Rationale**: `argparse` is stdlib (Constitution IV — no new dep). Moving bodies
to `cli.py` keeps `__main__` trivially within limits and makes the commands
unit-testable. Splitting `_print_items` out of `_run_poll` keeps both under the
statement/branch ceilings.

**Alternatives considered**: `click`/`typer` — new dependencies, rejected.
Keeping dispatch in `__main__` — risks the module/function limits and is harder
to test.

## D8 — Breaking change, no migration, no back-compat

**Decision**: Remove the scalar keys (`watched_repos`, `trigger_label`,
`jira_project`, `jira_jql_filter`, `jira_base_url`, `jira_auth`, `jira_email`,
`jira_repo_field`, `code_host*`, `reconcile_interval_seconds`,
`jira_poll_interval_seconds`) outright — no alias, no deprecation shim. Because
`extra="ignore"` is set on `Settings`, a stale `KESTREL_*` key simply has no
effect (it won't crash startup). Retarget the two "half-configured" warning
validators at the new model. No DB migration (config-only).

**Rationale**: The maintainer accepted the break (single-user tool). `extra=
"ignore"` means leftover env keys are inert rather than fatal, which is the
desired "old keys no longer honoured" behaviour (FR-006). The startup warnings
still surface a source that can't authenticate (spec Edge Cases).

## D9 — Quality-limit strategy (mechanical gate)

**Decision**: Anticipated pressure points and their splits are pre-planned:
`_resolve_repo` → 5 small helpers (D6); `JiraClient.search` already split in
change set A; CLI split into `_run_poll` + `_print_items` (D7); config models
extracted to `config_models.py` if `config.py` nears 500 lines. Per-source
service instances (D4) keep each `run_cycle`/`list_work_items` small. Every new
function targets ≤10 complexity, ≤5 returns, ≤12 branches, ≤5 args, ≤15 locals,
≤40 statements; new files carry no exemptions.

**Rationale**: The harness blocks on these mechanically (per-file at edit time
and in `task quality`); planning the splits up front avoids mid-implementation
rework.
