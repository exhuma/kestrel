---
description: "Task list for Task-source configuration abstraction & poll tooling"
---

# Tasks: Task-source configuration abstraction & poll tooling

**Input**: Design documents from `.specify/specs/004-task-source-config/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: INCLUDED — Constitution III (Test-First Discipline) requires behaviour
changes to ship with pytest. Test tasks precede the implementation they cover
within each phase.

**Baseline**: Change set A (Jira `/search/jql` migration + `host`/`port`/`reload`
Settings fields) has already shipped; these tasks build on it.

**Organization**: Grouped by user story. Each story is an independently testable
increment. Every new function must stay within the mechanical quality limits
(complexity ≤10, branches ≤12, returns ≤5, args ≤5, statements ≤40, locals ≤15,
module ≤500 lines, jscpd ≤3%); new files get no exemptions.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 (setup/foundational/polish carry no story label)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Make room for the new config models under the 500-line module limit.

- [ ] T001 Create `backend/app/config_models.py` and move `BackendConfig` into it, re-exported from `backend/app/config.py` (mechanical extraction, no behaviour change) so `config.py` has room for `TaskSourceConfig`; run the pinned `ruff`/`pylint` per-file checks after the move.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The task-source config model + Settings surface every story builds
on. **Additive** — old scalar keys are left in place here so the suite stays
green; they are removed inside US1/US4.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [ ] T002 Add `TaskSourceConfig` to `backend/app/config_models.py`: `type` discriminator (`Literal["github","jira"]`), per-type fields (github: `watched_repos`, `trigger_label`; jira: `base_url`, `auth`, `email`, `jql`, `key`, `repo_field`, `repo_link_text`, `code_host`, `code_host_base_url`, `code_host_token_env`), `token_env` with per-type default, a `@model_validator` enforcing per-type required fields (github ⇒ non-empty `watched_repos`; jira ⇒ `base_url`+`jql`+`key`; unknown type ⇒ error), and `token()` / `code_host_token()` helpers (mirroring `BackendConfig.secret()`). The jira `key` is the issue-key prefix used only for dismissal scoping (FR-007a). Per data-model.md.
- [ ] T003 In `backend/app/config.py`, add `task_sources: list[TaskSourceConfig] = []` as **file-only** (add to `_FILE_ONLY_FIELDS`; build from `data["task_sources"]` in `_apply_config_file`) and `poll_interval_seconds: int = 300` as an applicative key (add it to `_CONFIG_FILE_FIELDS` so it is settable in `config.toml`, not env-only).
- [ ] T004 In `backend/app/config.py`, add Settings helpers `github_sources()`, `jira_sources()` (filter `task_sources` by type) and `github_source_for(repo)` (the github entry whose `watched_repos` contains `repo`).
- [ ] T005 [P] Add config tests in `backend/tests/test_config.py`: `[[task_sources]]` parsing from a TOML overlay (including **multiple entries and two of the same type** — SC-002), per-type validation errors (unknown/missing `type`, github missing repos, jira missing `base_url`/`jql`/`key`), `token()` env resolution, `poll_interval_seconds` default + override **via config.toml** (proves it is applicative, not env-only), and the `github_source_for` helper.

**Checkpoint**: New config model + fields load and validate; existing suite still green (old keys untouched).

---

## Phase 3: User Story 1 - Configure every task source the same way (Priority: P1) 🎯 MVP

**Goal**: Both a GitHub and a Jira source are configured through `[[task_sources]]`;
all consumers read the list; the removed scalar selection keys are gone; observable
ingestion behaviour is unchanged (SC-006).

**Independent Test**: With one github + one jira entry, start the service — both
loops enable and ingest exactly as before; no scalar selection keys remain.

### Tests for User Story 1

- [ ] T006 [P] [US1] Update reconcile tests (`backend/tests/test_reconcile*.py`) to construct `ReconcileService` from a github `TaskSourceConfig`; assert unchanged reconcile + dismissal-clear behaviour.
- [ ] T007 [P] [US1] Update `backend/tests/test_jira_poll.py` to construct `JiraPollService` from a jira `TaskSourceConfig` (whole `jql`, no `jira_project`); assert unchanged poll behaviour.
- [ ] T008 [P] [US1] Update GitHub webhook tests (`backend/tests/test_github_webhook*.py`) for source-driven `watched` + `trigger_label` (via `github_source_for`).
- [ ] T009 [P] [US1] Update workflow/ingestion tests for the `task_sources`-driven source/code-host registry and `is_watched`.

### Implementation for User Story 1

- [ ] T010 [US1] Reshape `ReconcileService` in `backend/app/services/reconcile.py` to take one github `TaskSourceConfig` (repos + label + client); extract `_list_labelled(repo)`; scope dismissal-clear to this source's repos; `run_forever` sleeps on `settings.poll_interval_seconds`; update `get_reconcile_service` to build one service per github source.
- [ ] T011 [US1] Reshape `JiraPollService` in `backend/app/services/jira_poll.py` to take one jira `TaskSourceConfig` (client + `jql` + `key` + resolution config + its code host); replace `_jql()` with the entry's whole `jql`; scope the dismissal-clear via the entry's `key` prefix (`f"{entry.key}-"`, replacing the removed `jira_project` prefix — FR-007a); extract `_search_tasks()`; `run_forever` sleeps on `settings.poll_interval_seconds`; update `get_jira_poll_service` to build one service per jira source — client from the entry (token via `token()`) **and the code host built from the entry's `code_host*` fields** (feed `_build_code_host` from the entry, not removed top-level settings — U1).
- [ ] T012 [US1] Update `IngestionService.is_watched` in `backend/app/services/ingestion.py` to test `repo` against every `settings.github_sources()` allow-list.
- [ ] T013 [US1] Update `backend/app/routers/github_webhook.py` to resolve `watched` + trigger-label via `settings.github_source_for(repo)` and that entry's `trigger_label`.
- [ ] T014 [US1] Update `get_workflow_service()` in `backend/app/services/workflows.py` to build the `sources` / `code_hosts` registry by scanning `task_sources` (github entries → GitHub adapters; jira entries → Jira `TaskSource` + the entry's configured code host via `_build_code_host` fed from the entry).
- [ ] T015 [US1] Update the lifespan in `backend/app/main.py` to start one reconcile loop per `github_sources()` entry and one poll loop per `jira_sources()` entry (cancel all on shutdown). *(US2 later refactors this to `configured_poll_sources`.)*
- [ ] T016 [US1] Remove the superseded scalar selection keys from `Settings` in `backend/app/config.py` (`watched_repos`, `trigger_label`, `jira_project`, `jira_jql_filter`, `jira_base_url`, `jira_auth`, `jira_email`, `jira_repo_field`, `code_host`, `code_host_base_url`, `code_host_token`) and retarget the two "half-configured" warning validators to iterate `task_sources` (warn on a jira entry whose `token()` is unset, or a gitlab/gitea entry missing base URL/token).
- [ ] T017 [US1] Run `cd backend && uv run pytest -q` and `task quality`; confirm ingestion behaviour is preserved (SC-006) and all limits pass.

**Checkpoint**: The abstraction works end-to-end; existing GitHub + Jira ingestion behave identically on the new config.

---

## Phase 4: User Story 2 - Dry-run the poll (Priority: P2)

**Goal**: `python -m app poll` lists what every configured source matches (ref,
title, resolved repo), starting no runs.

**Independent Test**: With sources configured, run `python -m app poll` — items
from all sources print; no run is created and no write-back occurs.

### Tests for User Story 2

- [ ] T018 [P] [US2] Add `backend/tests/test_poll_source.py`: `list_work_items` on both services returns items and calls no `maybe_start_run`; `configured_poll_sources` yields one entry per configured source and none when empty.
- [ ] T019 [P] [US2] Add `backend/tests/test_cli.py`: `poll` prints items for all sources and exits 0 (and the "no sources configured" case exits 0); `serve` is the default subcommand; no run is created by `poll`.

### Implementation for User Story 2

- [ ] T020 [US2] Add `backend/app/services/poll_source.py`: `WorkItem` dataclass (`source`, `ref`, `title`, `code_repo`, `base_branch`), `PollSource` Protocol (`name`, `async list_work_items()`), and `configured_poll_sources(settings)` (one entry per configured `task_sources` element).
- [ ] T021 [US2] Add `list_work_items()` to `ReconcileService` (`backend/app/services/reconcile.py`) reusing `_list_labelled`; returns `WorkItem`s, starts no run.
- [ ] T022 [US2] Add `list_work_items()` to `JiraPollService` (`backend/app/services/jira_poll.py`) reusing `_search_tasks()` + `_resolve_repo`; starts no run; marks unresolved repos as `code_repo=None`.
- [ ] T023 [US2] Add `backend/app/cli.py`: `build_parser()` (subparsers `serve` [default via `set_defaults`] + `poll`), `cmd_serve(settings)` (uvicorn launch reading `settings.host/port/reload`), `cmd_poll(settings)` → `asyncio.run(_run_poll(settings))`, `_run_poll` (iterate `configured_poll_sources`, `await list_work_items`, hand to `_print_items`), `_print_items(name, items)`, and `main(argv=None) -> int`.
- [ ] T024 [US2] Shrink `backend/app/__main__.py` to `from app.cli import main` + `raise SystemExit(main())`.
- [ ] T025 [US2] Refactor the lifespan in `backend/app/main.py` to start loops via `configured_poll_sources(settings)` (DRY with T015), one `run_forever` task per source.

**Checkpoint**: Operator can dry-run every source; live loops and the CLI share one query path.

---

## Phase 5: User Story 3 - Resolve a Jira RFC's repository from a web link (Priority: P3)

**Goal**: A Jira RFC resolves its repo from a title-matched web/remote link when
no custom field is set; the field becomes optional.

**Independent Test**: With `repo_field` unset and a "Repository" web link on an
RFC, `python -m app poll` resolves the correct `owner/name`.

### Tests for User Story 3

- [ ] T026 [P] [US3] Add tests in `backend/tests/test_jira_repo_resolution.py`: `_repo_from_url` (github, gitlab subgroup, trailing `.git`, non-repo junk → None); web-link fallback used when field empty; link-title match is case-insensitive; neither field nor link ⇒ unresolved.
- [ ] T027 [P] [US3] Add a `get_remote_links` test in `backend/tests/test_jira_client.py` (hits `/issue/{key}/remotelink`, returns the raw list).

### Implementation for User Story 3

- [ ] T028 [US3] Add `JiraClient.get_remote_links(key)` in `backend/app/services/jira.py` (`GET /issue/{key}/remotelink`, returns the raw list; parsing stays out of the client).
- [ ] T029 [US3] Add module-level pure `_repo_from_url(url)` in `backend/app/services/jira_poll.py` (stdlib `urllib.parse`; trim `.git`; truncate GitLab `/-/` deep-links; `<2` path segments ⇒ `None`). Per contracts/jira-remote-link.md.
- [ ] T030 [US3] Split `_resolve_repo` in `backend/app/services/jira_poll.py` into `_repo_ref` (field when configured, else `_repo_ref_from_links`), `_repo_ref_from_links` (fetch links, case-insensitive `repo_link_text` match, `_repo_from_url`), `_split_repo_ref` (`owner/name[@base]`), and `_probe` (default-branch reachability); make `repo_field` optional. Each helper within limits.

**Checkpoint**: Repo resolvable via field or web link, identically downstream.

---

## Phase 6: User Story 4 - One cadence for re-checking sources (Priority: P3)

**Goal**: A single `poll_interval_seconds` governs both loops; the two old
per-source interval keys are gone.

**Independent Test**: Set only `poll_interval_seconds`; both loops re-check on it;
a leftover `KESTREL_RECONCILE_INTERVAL_SECONDS` has no effect.

### Tests for User Story 4

- [ ] T031 [P] [US4] Add a test (in `backend/tests/test_config.py`) asserting a leftover old interval env key is inert and `poll_interval_seconds` (default or set) is what both `run_forever`s read.

### Implementation for User Story 4

- [ ] T032 [US4] Remove `reconcile_interval_seconds` and `jira_poll_interval_seconds` from `Settings` (`backend/app/config.py`) and from `_CONFIG_FILE_FIELDS`; confirm both `run_forever` loops (reshaped in T010/T011) sleep on `settings.poll_interval_seconds`.

**Checkpoint**: Exactly one interval setting remains (SC-005).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation + example configs + final validation (FR-017).

- [ ] T033 [P] Rewrite `config.toml.example` to the `[[task_sources]]` shape + `poll_interval_seconds` (remove the old scalar keys).
- [ ] T034 [P] Update `backend/.env.example`: token env-var names (`KESTREL_GITHUB_TOKEN`, `KESTREL_JIRA_API_TOKEN`, `KESTREL_CODE_HOST_TOKEN`), remove the migrated scalar selection/interval keys, keep the change-set-A `KESTREL_HOST/PORT/RELOAD`.
- [ ] T035 [P] Rewrite the config surface in `docs/configuration.md` (task-source list, unified interval, removed keys, poll command).
- [ ] T036 [P] Update `docs/setup-jira-workflow.md` (web-link repo option + `python -m app poll`) and `docs/setup-github-workflow.md` (github source entry shape).
- [ ] T037 Run `cd backend && uv run pytest -q` and `task quality` green; execute the `quickstart.md` scenarios (US1–US4) end-to-end.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)**: none — start immediately.
- **Foundational (T002–T005)**: depends on Setup — BLOCKS all user stories.
- **US1 (T006–T017)**: depends on Foundational. This is the MVP and the base the
  other stories extend.
- **US2 (T018–T025)**: depends on US1 (reshaped services expose the reused query
  methods; T025 refactors the T015 lifespan).
- **US3 (T026–T030)**: depends on US1 (the `_resolve_repo` it splits was reshaped
  in T011). Independent of US2.
- **US4 (T031–T032)**: depends on US1 (T010/T011 already sleep on
  `poll_interval_seconds`). Independent of US2/US3.
- **Polish (T033–T037)**: after all desired stories.

### Within a story

- Tests (T006–T009, T018–T019, T026–T027, T031) are written first and fail
  before their implementation tasks.
- Same-file tasks are sequential (e.g. `jira_poll.py`: T011 → T022 → T029 → T030).

### Parallel Opportunities

- Foundational tests (T005) run alongside T002–T004 authoring once the model exists.
- US1 test-writing tasks T006, T007, T008, T009 are all [P] (different test files).
- US2 T018 and T019 are [P]; US3 T026 and T027 are [P].
- Polish T033–T036 are all [P] (different docs/example files).

---

## Parallel Example: User Story 1 tests

```bash
# Write these together (different files), ensure they fail first:
Task: "Update reconcile tests for github TaskSourceConfig (T006)"
Task: "Update jira poll tests for jira TaskSourceConfig (T007)"
Task: "Update github webhook tests for source-driven watched/label (T008)"
Task: "Update workflow/ingestion tests for task_sources registry (T009)"
```

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1.
2. **STOP and VALIDATE**: both sources configured via `[[task_sources]]`, existing
   ingestion behaviour preserved, `task quality` + pytest green (SC-001, SC-006).

### Incremental Delivery

1. US1 (MVP) → US2 (poll CLI, SC-003) → US3 (web-link repo, SC-004) → US4 (single
   interval, SC-005). Each adds value without breaking prior stories.
2. Polish (docs/examples) can trail each story or land at the end (FR-017).

### Notes

- [P] = different files, no incomplete-task dependency.
- Verify each new/split function against the pinned `ruff@0.15.20` + `pylint@4.0.6`
  per-file checks (the same the `agent-check.sh` hook / `task quality` run).
- Commit after each task or logical group; stop at any checkpoint to validate a
  story independently.
