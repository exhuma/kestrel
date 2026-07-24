# Implementation Plan: Task-source configuration abstraction & poll tooling

**Branch**: `004-task-source-config` | **Date**: 2026-07-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `.specify/specs/004-task-source-config/spec.md`

## Summary

Extract the per-source ingestion configuration that features 002 (GitHub) and
003 (Jira) accreted as divergent scalar keys into **one uniform, file-only
`[[task_sources]]` list**, where each entry names a `type` and carries that
type's selection criteria; folds the two per-source poll cadences into a single
`poll_interval_seconds`; broadens Jira repository resolution to accept a
**web/remote link** (title-matched) in addition to the existing custom field;
and adds a read-only **`python -m app poll`** command that lists what every
configured source currently matches, starting no runs. Secrets stay in the
environment — each entry names the env var holding its token (the existing
`BackendConfig`/`api_key_env` pattern). All existing consumers (webhook
acceptance, GitHub reconcile, Jira poll, run→source/code-host routing, and the
lifespan enablement gates) are rewired to read the list, with **no observable
change to ingestion behaviour**. This is the planned "extract the abstraction
when the second source lands" step; two concrete sources now exist, so the
extraction is justified under Constitution IV. It is a **breaking config
change** with no back-compat shim (accepted by the maintainer). **No schema
change** (the dismissal store is already source-neutral from 003) and **no new
runtime dependency** (`urllib.parse` + `argparse` are stdlib).

## Technical Context

**Language/Version**: Python 3.12 (backend, `uv`). No frontend change.

**Primary Dependencies**: FastAPI, pydantic-settings (config + TOML overlay),
`httpx` (existing Jira/GitHub clients). No new runtime dependency — URL parsing
uses stdlib `urllib.parse`; the CLI dispatch uses stdlib `argparse`.

**Storage**: SQLite via SQLAlchemy 2.x, Alembic-owned. **No migration**: task
sources are configuration only, and the dismissal store is already keyed by the
source-neutral `task_ref` (feature 003, migration 0007).

**Testing**: pytest with `httpx` MockTransport for the Jira/GitHub clients and
stubbed services (no real `claude`, no real Jira/GitHub, no production DB).

**Target Platform**: Linux server / local dev (`python -m app`), plus the
bundled Docker image.

**Project Type**: web-service backend + operator CLI (single entrypoint).

**Performance Goals**: N/A (personal single-user tool; poll cadence in the
hundreds of seconds). The dry-run poll must fully enumerate paginated Jira
results.

**Constraints**: Mechanical code-quality limits — per function complexity ≤10,
branches ≤12, returns ≤5, args ≤5, statements ≤40, locals ≤15; module ≤500
lines; jscpd ≤3%. New files get **no** grandfather exemptions. Loopback/access
model unchanged (the poll command is a local CLI, not an endpoint).

**Scale/Scope**: A handful of configured sources; the list must *support* more
than one entry per type without special-casing, but no multi-instance features
beyond what naturally falls out of a list are added.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.2.0. Re-checked
after Phase 1 — see "Post-Design Re-check".*

- **I. Contract Fidelity** — PASS. The breaking config change (removed scalar
  keys) is recorded here and in the spec (FR-006/FR-008) and will be reflected in
  `docs/configuration.md` + the example files. **No frontend type contract is
  touched** — no backend JSON shape served to the SPA changes; the feature is
  backend config + an operator CLI. No new stack deviation is introduced (the
  access model is unchanged; the poll command is loopback-local by nature).
- **II. Layered, Backend-Owned Architecture** — PASS. Logic stays in services;
  the CLI is a thin entrypoint that calls services (CLI → services → stores).
  **No `create_all`/raw DDL, no migration** — config-only change.
- **III. Test-First Discipline** — PASS (planned). Every behaviour change ships
  pytest: config parsing/validation of `[[task_sources]]`, token resolution,
  the unified interval, web-link URL parsing + resolution fallback, the
  non-ingesting `list_work_items` on both services, the rewired
  webhook/reconcile/lifespan gating, and the `poll` command. Existing 002/003
  behaviour tests are updated to the new config shape and MUST still pass
  (SC-006).
- **IV. Deliberate Simplicity & Single-User Scope** — PASS with justification.
  The `[[task_sources]]` abstraction is **not** speculative: it is the
  002-era "seam now, extract with the second source" decision executing now that
  two concrete sources exist. It removes redundancy rather than adding
  generality. No new dependency. Multiple-entries-per-type is an inherent
  property of a list, not an added feature. See Complexity Tracking for the one
  item worth recording (per-source code-host config).
- **V. Kit-Aligned Consistency & Observability** — PASS. `resolve_kits` was run
  for this task. Secrets stay in the environment — **no token ever written to
  the TOML file** (reusing the `api_key_env` pattern), honouring the ".env stays
  out of VCS" rule. Structured logging and the startup misconfiguration warnings
  are preserved/retargeted. `.env.example` + `config.toml.example` +
  `docs/configuration.md` are updated (documented template).

**Result**: PASS. No unjustified violations; proceed to Phase 0.

### Post-Design Re-check (after Phase 1)

Re-evaluated against the generated `data-model.md` / `contracts/` — still PASS.
The design adds **no** database entity or migration, **no** new runtime
dependency (`urllib.parse`, `argparse` are stdlib), and **no** off-loopback
surface (the `poll` command is a local CLI). Secrets remain env-only via
`token_env`. The only recorded complexity (per-source code-host config, D3) is
justified in Complexity Tracking. The two accepted breaking removals are scoped
and, thanks to `extra="ignore"`, do not turn a stale key into a crash. No new
Constitution deviation requires an amendment.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/004-task-source-config/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── config-schema.md      # [[task_sources]] + poll_interval_seconds contract
│   ├── cli-poll.md           # `python -m app poll` command contract
│   └── jira-remote-link.md   # web-link repo-resolution contract
├── checklists/
│   └── requirements.md  # spec quality checklist (already passing)
└── tasks.md             # /speckit-tasks output (NOT created here)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── config.py                 # + TaskSourceConfig, task_sources, poll_interval_seconds;
│   │                             #   remove scalar keys; retarget warning validators
│   ├── config_models.py          # NEW: houses BackendConfig + TaskSourceConfig
│   │                             #   (extracted for cohesion + 500-line headroom)
│   ├── cli.py                    # NEW: argparse dispatch (serve|poll), command bodies
│   ├── __main__.py               # thin shim -> app.cli.main
│   ├── services/
│   │   ├── poll_source.py        # NEW: WorkItem, PollSource protocol, configured_poll_sources()
│   │   ├── jira.py               # + get_remote_links(); _repo_from_url() parser
│   │   ├── jira_poll.py          # source-driven; _resolve_repo split; _search_tasks; list_work_items
│   │   ├── reconcile.py          # source-driven; _list_labelled; list_work_items
│   │   ├── ingestion.py          # is_watched() over task_sources
│   │   └── workflows.py          # get_workflow_service() source/code-host registry from task_sources
│   ├── routers/github_webhook.py # watched/trigger-label from the matching github source
│   └── main.py                   # lifespan starts a loop per configured_poll_sources() entry
└── tests/                        # config/jira/poll/reconcile/webhook/cli tests (new + updated)

config.toml.example               # [[task_sources]] + poll_interval_seconds
backend/.env.example              # token env-var names; remove migrated scalar keys
docs/configuration.md             # rewritten config surface
docs/setup-jira-workflow.md       # web-link repo option + poll command
docs/setup-github-workflow.md     # github source entry shape
```

**Structure Decision**: Single backend package with an operator CLI. The
existing `@lru_cache` singleton-factory + FastAPI app-factory/lifespan pattern is
kept; the new source-agnostic listing lives in a service module
(`services/poll_source.py`), not `ports.py` (which models *run-time*
TaskSource/CodeHost roles, distinct from *poll-time* listing). `config.py` is at
~378 lines after change set A; the config models (`BackendConfig` +
`TaskSourceConfig`) are extracted to `config_models.py` for cohesion and
500-line headroom (a mechanical extraction, no behaviour change).

## Complexity Tracking

> Only the items worth recording under Principle IV; neither is a violation.

| Item | Why Needed | Simpler Alternative Rejected Because |
|------|------------|--------------------------------------|
| `[[task_sources]]` list abstraction | Two concrete sources (GitHub, Jira) already exist with divergent, redundant scalar config; extracting the shared shape is the planned 002 decision and removes redundancy. | Keeping per-source scalar keys is the status quo being fixed — it does not scale to GitLab/Planka and duplicates the "which items qualify" idea twice. |
| Per-source code-host config on the Jira entry (vs one global) | The resolved-repo code host is a property of a Jira source; putting it on the entry keeps each source self-describing and lets future Jira sources target different hosts, matching the abstraction's intent. | A single global `code_host` would re-introduce exactly the kind of source-specific top-level scalar this feature removes, and would silently break with two Jira sources on different hosts. |
