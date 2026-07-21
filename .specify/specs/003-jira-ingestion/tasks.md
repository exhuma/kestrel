---
description: "Task list for Jira Ingestion & Autonomous Design/Code/Verify Loop"
---

# Tasks: Jira Ingestion & Autonomous Design/Code/Verify Loop

**Input**: Design documents from `/.specify/specs/003-jira-ingestion/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — Constitution III (Test-First Discipline, NON-NEGOTIABLE) makes tests
mandatory for every behaviour change. Write each story's tests first and see them fail before
implementing. All tests mock the Jira/GitHub/GitLab `httpx` transport, the agent backends, and
the check-runner subprocess — no real `claude`, no real Jira/GitLab, no production DB.

**Organization**: Grouped by user story. The cross-cutting skeleton (ports, `task_ref` identity,
schema, self-hostable code host, check runner, source-neutral workflow) lives in **Foundational**
— it blocks every story. Priority order: US1 (P1 Jira ingestion), US2 (P1 refine/PRD via Jira),
US3 (P1 autonomous loop + evidence), US4 (P2 unified-workflow verification + frontend), US5 (P3
resilience & webhook seam).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4 / US5
- Backend tests are flat `backend/tests/test_*.py`; frontend tests live under
  `frontend/tests/<area>/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration surface the Jira ingestion, poll, code host, verify loop, and notifier
all read.

- [X] T001 Add Jira, code-host, and verify settings to `backend/app/config.py` (env prefix `KESTREL_`): `jira_base_url`, `jira_auth: Literal["basic","bearer"] = "basic"`, `jira_email`, `jira_api_token` (secret), `jira_project`, `jira_jql_filter = ""`, `jira_repo_field`, `jira_poll_interval_seconds = 300`; `code_host: Literal["github","gitlab","gitea"] = "github"`, `code_host_base_url = ""`, `code_host_token = ""` (secret, falls back to `github_token` for github); `verify_checks: list[str] = []`; `max_verify_iterations = 3`; plus `model_validator`s that warn when `jira_base_url` is set without `jira_project`/`jira_api_token`, and when `code_host` is a self-hosted type without `code_host_base_url`/`code_host_token`
- [X] T002 [P] Write config tests in `backend/tests/test_config.py`: Jira + code-host + `verify_checks` defaults; `jira_auth`/`code_host` accept their literals; both partial-config warnings fire; `jira_api_token`/`code_host_token` never echoed in `repr`/logs; `verify_checks` parses a JSON list
- [X] T003 [P] Document the new `KESTREL_JIRA_*`, `KESTREL_CODE_HOST_*`, `KESTREL_VERIFY_CHECKS`, and `KESTREL_MAX_VERIFY_ITERATIONS` settings in `backend/.env.example` and `docs/configuration.md` (tokens never committed; note the self-hosted-git posture)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The `task_ref` identity, schema/migration, Task Source / Code Host ports (incl. a
self-hosted-git code host), the verify check runner, and the source-neutral unified-workflow
skeleton every story builds on.

**⚠️ CRITICAL**: No user story can start until this phase is complete.

### Identity & schema

- [X] T004 Add `task_ref: str = ""` to `WorkflowRun`, make `issue_number: int | None`, and build steps as `["refine", "design", "code", "verify"]` in `backend/app/models_workflow.py`
- [X] T005 In `backend/app/persistence/tables.py`: add `workflow_run.task_ref` (String, server_default `""`), make `workflow_run.issue_number` nullable, and re-key `issue_dismissal` from `(repo, issue_number)` to a single `task_ref` PK
- [X] T006 Create Alembic migration `backend/alembic/versions/0007_jira_ingestion.py` (`down_revision = "0006"`): add + backfill `workflow_run.task_ref` (`repo || '#' || issue_number`); make `issue_number` nullable (SQLite `batch_alter_table`); rebuild `issue_dismissal` with a `task_ref` PK (backfill); `downgrade()` reverses all three
- [X] T007 Persist and rehydrate `task_ref` (and `issue_number = None`) in `backend/app/persistence/workflow_store.py` (`save` upsert + `load_all` rebuild)
- [X] T008 [P] Extend `backend/tests/test_workflow_persistence.py`: `task_ref` round-trips; a Jira run rehydrates with `issue_number is None`; a GitHub run keeps its number
- [X] T009 Generalize `DismissalStore` to `add(task_ref)`, `is_dismissed(task_ref) -> bool`, `clear(task_ref)`, and preserve/expose the enumeration the reconcile/poll clear paths use (e.g. `all() -> list[str]` of dismissed `task_ref`s) so a cycle can clear dismissals whose ticket no longer qualifies (FR-033), in `backend/app/persistence/dismissal_store.py`
- [X] T010 [P] Update `backend/tests/test_dismissal_store.py` to the `task_ref` key: `add`→`is_dismissed` true, `clear`→false, durable across a fresh store instance; `all()` enumerates current dismissals (used by the poll/reconcile clear paths)
- [X] T011 [P] Write `backend/tests/test_migration_0007.py`: `upgrade` backfills `task_ref` and the dismissal PK; `downgrade` restores the prior shape (in-memory SQLite)

### Task Source / Code Host ports (incl. self-hosted git)

- [X] T012 [P] Define `Task`, `Observation` (`kind: Literal["http","ui","check"]`), `Evidence` dataclasses and the `TaskSource` / `CodeHost` `Protocol`s in `backend/app/ports.py` per `contracts/task-source-port.md`, `contracts/code-host-port.md`, `contracts/verify-evidence.md` (the generic `Observation{kind}` shape carries the assumed behavioural harness's output so it drops in later)
- [X] T013 Split `backend/app/services/github.py` into `GitHubTaskSource` (`get_task`, `post_comment`, `attach` no-op, `publish_refined` → `update_issue` + sentinel, `list_open` → `list_issues_by_label`, `deep_link_ref`) and `GitHubCodeHost` (`get_default_branch`, `open_change_request` → `create_pull_request` with `Closes #{n}` body, `clone_remote` → `f"{git_base}/{repo}.git"`) over the existing `GitHubClient` (HTTP calls unchanged)
- [X] T014 [P] Write `backend/tests/test_github_ports.py`: `GitHubTaskSource.publish_refined` routes to `update_issue` with the sentinel; `GitHubCodeHost.open_change_request` opens a draft PR with `Closes #{n}`; `clone_remote` composes `git_base/repo.git`; parity with pre-split behaviour (httpx mocked)
- [X] T015 Implement `GitLabCodeHost` in `backend/app/services/gitlab.py` (self-hosted GitLab; `get_default_branch` via `GET /projects/{id}`, `open_change_request` → `POST /projects/{id}/merge_requests` with a `Draft:` title for drafts and an RFC-key body, `clone_remote` → `f"{code_host_base_url}/{repo}.git"`; PAT auth), and extend `GitService._auth` (`backend/app/services/git.py`) to accept a per-run remote/token so a self-hosted host works alongside GitHub
- [X] T016 [P] Write `backend/tests/test_gitlab_code_host.py`: `open_change_request` opens an MR (draft prefix, RFC-key body); `get_default_branch` returns the branch and raises on an unreachable project; `clone_remote` uses `code_host_base_url`; the token never appears in logs (httpx mocked)

### Verify evidence gatherer (v1 interim; behavioural harness deferred)

- [X] T017 Implement the v1 interim evidence gatherer `CheckRunner.run(workspace) -> Evidence` in `backend/app/services/checks.py`: run each `settings.verify_checks` command in the worktree cwd (existing subprocess helper, bounded timeout), map exit code → `passed`, emit `Observation(kind="check", name, detail=<bounded output>)`; return `Evidence([])` when unconfigured; log which checks ran without echoing secrets. NOTE: the assumed behavioural harness (run the app + exercise via HTTP/Playwright → `kind="http"`/`"ui"` observations, with boundary detection) is **designed-for but out of scope for this feature** (FR-015b) — it returns the same `Evidence`, so it drops in without workflow change
- [X] T018 [P] Write `backend/tests/test_check_runner.py`: runs each configured command in cwd, maps exit code → `passed`, bounds `detail`, `Evidence([])` when unconfigured; no secret in `detail`/logs (subprocess mocked)

### Policy & notifier (source-neutral)

- [X] T019 Update `backend/app/policy.py`: replace `plan`/`implement` keys with `design`/`code`/`verify` in `DEFAULT_MODELS` and `STEP_REQUIREMENTS` (`code` needs `FILE_EDITS`; `design`/`verify` are `TEXT`, run in the worktree cwd)
- [X] T020 In `backend/app/notifications.py`: make `render_message` source-neutral (single `{task}` placeholder fed by `run.task_ref`); add fixed thin templates for the new gate/boundary statuses (`escalated`, change-request-link), status + link only (FR-029)
- [X] T021 Replace `GitHubIssueNotifier` with `TaskSourceNotifier(sources: dict[str, TaskSource], public_base_url)` in `backend/app/notifications.py`: resolve `sources[run.source]`, render the thin template, append the deep-link, `post_comment` fire-and-forget (best-effort, swallow+log — FR-028)
- [X] T022 [P] Write `backend/tests/test_task_source_notifier.py`: a Jira run's comment goes through the Jira source, a GitHub run's through the GitHub source; body is thin + carries the deep-link; a raised `post_comment` is swallowed; `CompositeNotifier` still records the in-app row on failure

### Source-neutral unified workflow skeleton

- [X] T023 Generalize `WorkflowService.create(*, source, task_ref, code_repo, issue_number=None, base_branch=None)` in `backend/app/services/workflows.py`: set `repo=code_repo`, `task_ref`, steps `refine/design/code/verify`, branch per source (GitHub `kestrel/issue-{n}`, Jira `kestrel/{slug(task_ref)}`)
- [X] T024 Make `_drive`/`_continue` source-neutral in `backend/app/services/workflows.py`: resolve the run's `TaskSource`/`CodeHost` from `run.source`; fetch the task via `get_task`; resolve `base_branch` via `CodeHost.get_default_branch` when unset; provision the worktree from `CodeHost.clone_remote(code_repo)`
- [X] T025 Reshape the phases in `backend/app/services/workflows.py`: rename `plan`→`design` / `implement`→`code`, run `design` and `code` **gatelessly** (no `awaiting_*_approval`), introduce statuses `designing`/`coding`/`verifying`/`escalated`, and rename prompts `PLAN_PROMPT`→`DESIGN_PROMPT`, `IMPLEMENT_PROMPT`→`CODE_PROMPT`
- [X] T026 Add a `verify` phase (accept-only in this phase) in `backend/app/services/workflows.py`: after `code` diffs, gather `Evidence` (v1: `CheckRunner.run(run.workspace)`; the assumed behavioural HTTP/Playwright gatherer is a later drop-in), then run the `verifier` agent in the worktree cwd with `VERIFY_PROMPT` carrying PRD + design + diff + evidence (adjudicate observed behaviour vs the PRD), parse `<VERDICT>`, and on accept proceed to deliver (the reject→loop→escalation logic lands in US3)
- [X] T027 Update `_deliver` in `backend/app/services/workflows.py` to open the change request via `CodeHost.open_change_request(...)` (source/host-aware body) and post the CR-link comment through `_save`/the notifier
- [X] T028 Update the `get_workflow_service()` factory in `backend/app/services/workflows.py`: build `sources = {"github-issue": GitHubTaskSource(...), "manual": GitHubTaskSource(...)}` (the `"jira-issue"` entry is added in US1 by T035 — do **not** reference `JiraTaskSource` here, it does not exist until US1), select the Jira `CodeHost` from `settings.code_host` (`GitHubCodeHost`/`GitLabCodeHost`) while GitHub/manual runs use `GitHubCodeHost`, construct the `CheckRunner`, and compose `CompositeNotifier([InAppNotifier(...), TaskSourceNotifier(sources, public_base_url)])`. Register the `sources` map so an entry can be added by later phases
- [X] T029 Generalize `IngestionService.maybe_start_run(*, source, task_ref, code_repo, base_branch=None, title="")` in `backend/app/services/ingestion.py` (dedup/dismissal/one-run keyed on `task_ref`) and adapt the GitHub callers in `backend/app/routers/github_webhook.py` and `backend/app/services/reconcile.py` (`task_ref=f"{repo}#{issue_number}"`, `code_repo=repo`) with no behaviour change
- [X] T030 [P] Write `backend/tests/test_workflow_reshape.py`: `create` sets `task_ref`/steps; a GitHub-sourced run traverses `refining → awaiting_refine_approval → designing → coding → verifying → opening_pr → done`; `design`/`code`/`verify` never set an `awaiting_*` status; reconcile/webhook still start runs through the generalized entry point

**Checkpoint**: `task_ref` identity + migration `0007`, the Task Source / Code Host ports (incl.
`GitLabCodeHost`), the check runner, the source-dispatching notifier, and a source-neutral
unified workflow all exist and are tested; existing GitHub/manual runs work through the new
skeleton.

---

## Phase 3: User Story 1 - Auto-start a run from a Jira RFC (Priority: P1) 🎯 MVP

**Goal**: A qualifying RFC in the watched Jira project, with a resolvable repo field, starts
exactly one run targeting the resolved repo on the configured code host — no UI interaction. An
unresolvable repo starts no run and comments the reason on the RFC.

**Independent Test**: A stubbed qualifying RFC with a resolvable repo ⇒ one run
(`source="jira-issue"`, `repo=<resolved>`, `task_ref=<key>`); same RFC next cycle ⇒ still one;
empty/unreachable repo field ⇒ no run + `unresolved-repo` log + one RFC comment.

### Tests for User Story 1 (write first, ensure they fail)

- [X] T031 [P] [US1] Write `backend/tests/test_jira_client.py`: `search(jql)` parses issues→`Task`s honouring `fields`/`max_results`; `get_field` returns value / `None`; `add_comment`/`add_attachment` use the right verb/path/headers (`X-Atlassian-Token: no-check`); `basic` vs `bearer` auth; token never logged (httpx mocked)
- [X] T032 [P] [US1] Write `backend/tests/test_jira_repo_resolution.py`: a resolvable field ⇒ `(repo, base_branch)` reachable on the configured `CodeHost`; empty ⇒ `unresolved-repo`, no run, one comment; a repo the `CodeHost` probe cannot reach ⇒ `unresolved-repo`; a missing field on the schema ⇒ operator-misconfig log
- [X] T033 [P] [US1] Write `backend/tests/test_jira_poll.py`: a cycle starts exactly one run per qualifying RFC; a second cycle starts none (idempotent via the `task_ref` guard); a dismissed RFC still matching the JQL is skipped; a dismissed RFC that **no longer matches the JQL has its dismissal cleared** (re-trigger gesture, FR-033) and re-qualifying starts a fresh run; a Jira outage is logged and the loop continues

### Implementation for User Story 1

- [X] T034 [US1] Implement `JiraClient` (`search`, `get_issue`, `get_field`, `add_comment`, `add_attachment`; `basic`/`bearer` auth; `JiraError`) on `httpx` in `backend/app/services/jira.py`
- [X] T035 [US1] Implement `JiraTaskSource` (ports impl: `get_task`, `post_comment`→`add_comment`, `attach`/`publish_refined`→`add_attachment`, `list_open`→`search`, `deep_link_ref`) in `backend/app/services/jira.py`, and **register it in the `get_workflow_service()` factory `sources` map under `"jira-issue"`** (the entry T028 deliberately deferred to US1 — resolves the Foundational→US1 ordering)
- [X] T036 [US1] Implement repo resolution (`JiraClient.get_field(key, jira_repo_field)` → parse `owner/name[@base_branch]` → probe via the configured `CodeHost.get_default_branch`) in `backend/app/services/jira_poll.py`
- [X] T037 [US1] Implement `JiraPollService.run_forever()` (immediate cycle then sleep `jira_poll_interval_seconds`; JQL `project = "{jira_project}"` + optional `jira_jql_filter`; per RFC resolve repo then `ingestion.maybe_start_run(source="jira-issue", task_ref=key, code_repo=repo, base_branch=…, title=…)`; comment the RFC on unresolved repo; **clear the dismissal of any previously-dismissed Jira RFC that no longer appears in the qualifying result set** — the re-trigger gesture, mirroring the GitHub reconcile clear (FR-033); log each outcome) in `backend/app/services/jira_poll.py`
- [X] T038 [US1] Launch the Jira poll task in `backend/app/main.py` `_lifespan` (after `recover()`, before `yield`) only when `jira_base_url` and `jira_project` are set; track it and cancel on shutdown (mirrors the reconcile task)

**Checkpoint**: MVP — a Jira RFC autonomously starts one run against the resolved repo (on GitHub
or a self-hosted GitLab per config) and begins refining; unresolvable repos are surfaced.

---

## Phase 4: User Story 2 - Refine the RFC & gate PRD approval through Jira (Priority: P1)

**Goal**: Clarifications post a **thin** deep-link comment on the RFC (no questions); the human
answers in the kestrel questionnaire; on completion the PRD is **attached** to the RFC and a
thin approval notification is posted; approval unlocks design, rejection stops the run and
dismisses the RFC.

**Independent Test**: Force a clarification round ⇒ a deep-link-only comment, run holds; answer
in the UI ⇒ refinement resumes; completion ⇒ PRD attached + thin approval comment; approve ⇒
`designing`; reject ⇒ `rejected` + dismissal.

**Depends on**: US1 (uses `JiraTaskSource.attach`/`publish_refined`).

### Tests for User Story 2 (write first, ensure they fail)

- [ ] T039 [P] [US2] Write `backend/tests/test_refine_notifications.py`: `awaiting_refine_input` posts a thin comment carrying only the questionnaire deep-link (no question text); `awaiting_refine_approval` posts a thin approval comment; neither leaks refined/PRD content (FR-029)
- [ ] T040 [P] [US2] Write `backend/tests/test_prd_delivery.py`: on PRD approval, `publish_refined` attaches `PRD.md` for a Jira run and updates the issue (sentinel) for a GitHub run; PRD rejection ends the run `rejected` and writes a `task_ref` dismissal — stop-and-dismiss, not auto-return (FR-012)

### Implementation for User Story 2

- [ ] T041 [US2] On PRD approval in `_refine` (`backend/app/services/workflows.py`), call `TaskSource.publish_refined(run.task_ref, prd)` before entering `design` (Jira ⇒ attachment, GitHub ⇒ issue+sentinel — unchanged for GitHub)
- [ ] T042 [US2] Ensure the refine clarification + approval notifications are thin deep-link comments (verify the `TaskSourceNotifier`/template path carries no questionnaire or PRD content) in `backend/app/notifications.py`
- [ ] T043 [US2] Write a `task_ref` dismissal on PRD rejection (and on abandon) in `backend/app/services/workflows.py` (`reject`/`delete` paths)

**Checkpoint**: A human working only in Jira can clarify (via the linked form) and approve/reject
the PRD; the PRD lands as an attachment; nothing sensitive is posted to the ticket.

---

## Phase 5: User Story 3 - Run design → code → verify autonomously to a change request (Priority: P1)

**Goal**: After PRD approval, design/code/verify run gatelessly; the verifier adjudicates
**measurable evidence** (configured checks run in the worktree) plus the diff/PRD, and accepts or
returns work to the coder with feedback, bounded by `max_verify_iterations`; on acceptance a
change request is opened and its link posted to the RFC; on exhaustion the run escalates.

**Independent Test**: From an approved PRD, the loop runs with no `awaiting_*` gate; a failing
configured check forces a reject with the failing output in the coder's feedback; verifier
reject-once ⇒ coder re-runs then accept ⇒ change request opened + link on RFC; reject to the
limit ⇒ `escalated`, no change request, one escalation comment.

**Depends on**: Foundational verify skeleton (T026) and the check runner (T017).

### Tests for User Story 3 (write first, ensure they fail)

- [X] T044 [P] [US3] Write `backend/tests/test_verify_loop.py`: verdict parsing (`<VERDICT>{accept,feedback}</VERDICT>`); a failing `Observation` forces reject even if the model text says accept (invariant) and the failing observation `detail` is in the coder feedback; reject-then-accept ⇒ ≤2 rounds; reject to `max_verify_iterations` ⇒ `escalated`, no change request, one escalation comment; `design`/`code`/`verify` never enter an `awaiting_*` gate
- [X] T045 [P] [US3] Write `backend/tests/test_autonomous_no_gate.py`: a blocked coder (no diff / cannot proceed) escalates rather than parking on a human input gate (no `awaiting_implement_input`)

### Implementation for User Story 3

- [X] T046 [US3] Add `VERIFY_PROMPT` (carrying PRD + design + diff + evidence) and `<VERDICT>` parsing (accept + feedback) in `backend/app/services/workflows.py`
- [X] T047 [US3] Implement the bounded code↔verify loop in `backend/app/services/workflows.py`: enforce the failing-observation invariant (any failing `Observation` ⇒ reject); on reject with iterations remaining, re-run `code` with verifier feedback **including the failing observation `detail`** and increment the in-memory counter on the run's `_Control`; on accept, deliver
- [X] T048 [US3] Implement escalation in `backend/app/services/workflows.py`: on exhaustion set `escalated`, post the thin escalation comment via `_save`/notifier, teardown the workspace, open no change request
- [X] T049 [US3] Replace the old `awaiting_implement_input` blocked-coder gate with an escalation path (a coder that cannot proceed autonomously escalates — FR-020) in `backend/app/services/workflows.py`

**Checkpoint**: The design/code/verify loop is fully autonomous, evidence-grounded, bounded, and
ends in either a change request (link on the RFC) or an escalation comment.

---

## Phase 6: User Story 4 - One unified workflow across every task source (Priority: P2)

**Goal**: Prove and surface that Jira, GitHub, and manual runs traverse the identical workflow;
render the new phases/outcome in the UI without surfacing `source`.

**Independent Test**: A GitHub run and a Jira run traverse the identical status sequence
(differing only in notification surface and CR body/host); the UI names `design`/`code`/`verify`
and `escalated`; `source` is absent from the API/types.

**Depends on**: US1–US3 landed (to compare full traversal); the frontend part depends only on the
Foundational status set.

### Tests for User Story 4 (write first, ensure they fail)

- [ ] T050 [P] [US4] Write `backend/tests/test_source_parity.py`: a Jira run and a GitHub run produce the identical ordered status sequence and step set; only the notification surface (`post_comment` target) and the CR body/host differ; `WorkflowDetail` exposes no `source`/`task_ref`
- [ ] T051 [P] [US4] Write `frontend/tests/composables/useWorkflows.states.test.ts`: the status/step label + chip-tone maps resolve `designing`/`coding`/`verifying`/`escalated` and `design`/`code`/`verify`; `?run=<id>` still selects a run (HTTP/SSE mocked)

### Implementation for User Story 4

- [ ] T052 [US4] Extend the frontend status/step label + chip-tone maps for `designing`/`coding`/`verifying`/`escalated` and `design`/`code`/`verify`, using existing Vuetify theme tokens (no hard-coded colours) in `frontend/src/` (the workflow status/step display component/composable)
- [ ] T053 [US4] Confirm `source`/`task_ref` are not added to `frontend/src/types/` or the backend API schema (`backend/app/schemas.py`); the UI stays source-uniform (FR-026)

**Checkpoint**: One predictable workflow across every source, correctly rendered, with `source`
still internal.

---

## Phase 7: User Story 5 - Stay reliable across restarts & be webhook-ready (Priority: P3)

**Goal**: Exactly one run per RFC across cycles and restarts; transient loop states fail loudly
on restart; every RFC observation outcome is logged; the ingestion entry point stays the single
source-neutral call a future webhook could reuse.

**Independent Test**: Overlapping cycles / a simulated restart ⇒ one run per RFC; restart at
`awaiting_refine_approval` ⇒ re-parked, no duplicate comment; restart in `coding`/`verifying` ⇒
`failed`; each observation logs its outcome.

**Depends on**: Foundational + US1.

### Tests for User Story 5 (write first, ensure they fail)

- [ ] T054 [P] [US5] Write `backend/tests/test_jira_ingestion_recovery.py`: overlapping poll cycles ⇒ one run; restart with an in-flight/terminal run ⇒ no second run next cycle; `recover()` re-parks an `awaiting_refine_approval` Jira run without a duplicate comment; a run in `coding`/`verifying` is failed loudly on restart
- [ ] T055 [P] [US5] Write `backend/tests/test_ingestion_logging.py`: `maybe_start_run`/poll log each outcome (`started`/`skipped-duplicate`/`skipped-filtered`/`unresolved-repo`/`dismissed`/`failed`) with no credential in any line

### Implementation for User Story 5

- [ ] T056 [US5] Add `designing`/`coding`/`verifying` to `_TRANSIENT` and keep `escalated` terminal (with `done`/`failed`/`rejected`) in `backend/app/services/workflows.py` `recover()`
- [ ] T057 [US5] Emit structured per-observation outcome logs in `backend/app/services/ingestion.py` and `backend/app/services/jira_poll.py` (credentials redacted)
- [ ] T058 [US5] Confirm `maybe_start_run` is the single run-start entry point for both poll and (future) webhook, and add a short module docstring note in `backend/app/services/ingestion.py` marking the webhook seam (FR-034)

**Checkpoint**: Jira ingestion is idempotent, restart-safe, observable, and one caller away from
webhook support.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T059 [P] Update `docs/architecture.md`: add the Jira task source, the unified refine→PRD→design→code→verify workflow, the evidence-grounded verify loop + escalation, and the extracted `TaskSource`/`CodeHost` ports (GitHub + self-hosted GitLab code hosts); note ingestion is **poll-only** (no new off-loopback exception) and the sovereignty posture (self-hostable, no mandatory external cloud)
- [ ] T060 [P] Add `docs/setup-jira-workflow.md`: Jira config (base URL, auth, project, JQL, repo field), code-host config (`KESTREL_CODE_HOST` incl. self-hosted GitLab/Gitea), `KESTREL_VERIFY_CHECKS`, the re-trigger gesture (RFC leaving/re-entering the JQL), and that no inbound endpoint/tunnel is needed
- [ ] T061 Audit `backend/app/services/jira.py`, `gitlab.py`, `checks.py`, `jira_poll.py`, and `notifications.py` for structured-log coverage and confirm the Jira token, code-host token, and GitHub token never appear in any log line, check excerpt, or comment (FR-004/FR-009/SC-009)
- [ ] T062 Run the `quickstart.md` scenarios 1–6 end-to-end and record results
- [ ] T063 Run full gates: `cd backend && uv run pytest`, `cd frontend && npm run test`, and linters/formatters with no suppressions

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **Blocks every user story.**
- **US1 (Phase 3, P1)**: depends on Setup + Foundational. MVP.
- **US2 (Phase 4, P1)**: depends on Foundational **and US1** (`JiraTaskSource.attach`/`publish_refined`).
- **US3 (Phase 5, P1)**: depends on Foundational (extends the verify skeleton T026 + check runner T017).
- **US4 (Phase 6, P2)**: backend parity test depends on US1–US3; the frontend map work depends only on the Foundational status set.
- **US5 (Phase 7, P3)**: depends on Foundational + US1.
- **Polish (Phase 8)**: after the stories it documents/validates.

### Within each story

- Tests first (must fail before implementation).
- Model/schema (T004–T006) → stores (T007–T011) → ports + hosts + check runner (T012–T018) →
  policy/notifier (T019–T022) → workflow skeleton (T023–T030).
- `ports.py` (T012) + `github.py` split (T013) + `GitLabCodeHost` (T015) + `CheckRunner` (T017)
  before the factory wiring (T028) and the verify skeleton (T026).
- **No Foundational→US1 forward reference**: T028 wires only the `github-issue`/`manual` sources
  (GitHubTaskSource); T035 (US1) registers the `jira-issue` source once `JiraTaskSource` exists.
- Generalized `maybe_start_run` (T029) before the Jira poll (T037).
- The verify skeleton (T026) + check runner (T017) before the US3 loop/invariant/escalation
  (T047–T048).

### Parallel opportunities

- Setup: T002, T003 in parallel.
- Foundational: within-file-ordered tasks (T004–T007, T013, T015, T017, T019–T029) serialise per
  file; the test/def tasks T008, T010, T011, T012, T014, T016, T018, T022, T030 are `[P]`.
- US1 tests: T031, T032, T033 in parallel. US2: T039, T040. US3: T044, T045. US4: T050, T051.
  US5: T054, T055.
- **Cross-story caution**: US2 (T041–T043) and US3 (T046–T049) both edit
  `backend/app/services/workflows.py`; serialise those edits despite dependency-independence.

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together (distinct files):
Task: "Jira client tests in backend/tests/test_jira_client.py"                 # T031
Task: "Repo-resolution tests in backend/tests/test_jira_repo_resolution.py"    # T032
Task: "Jira poll tests in backend/tests/test_jira_poll.py"                      # T033
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1.
2. **STOP and validate**: a qualifying Jira RFC with a resolvable repo starts exactly one run
   against that repo (on the configured code host) and begins refining; unresolvable repos are
   surfaced (quickstart Scenario 1).
3. Shippable increment: autonomous Jira-triggered run start with repo resolution.

### Incremental delivery

1. Setup + Foundational → unified workflow skeleton + ports (incl. self-hosted GitLab code host) +
   check runner + `task_ref` (GitHub/manual still work).
2. US1 → Jira RFC starts a run (MVP).
3. US2 → clarifications + PRD approval routed thinly through Jira.
4. US3 → the fully autonomous, evidence-grounded design/code/verify loop → change request /
   escalation.
5. US4 → verified unification + UI naming of the new phases.
6. US5 → idempotency, restart-safety, observability, webhook seam.

Each story is independently testable; commit after each task or logical group.

---

## Notes

- [P] = different files, no incomplete dependency.
- Tests are mandatory (Constitution III); verify they fail before implementing. Mock the
  Jira/GitLab `httpx` transport, the agent backends, and the check-runner subprocess — no real
  `claude`, Jira/GitLab, or production DB.
- **No new runtime dependency** — the Jira and GitLab clients reuse `httpx`; the check runner
  reuses the existing subprocess helper.
- Ingestion is **poll-only**: no off-loopback endpoint is added, so **no constitution amendment**
  is required (contrast with feature 002). A future Jira webhook is one added caller of
  `maybe_start_run` (T058 marks the seam).
- **Sovereignty posture**: the code host is operator-configured and **self-hostable** — a
  Jira-resolved repo can live on a self-hosted GitLab (`KESTREL_CODE_HOST=gitlab`), not only
  GitHub.com. GitLab is the reference self-hosted impl (T015); Gitea/Forgejo is the same port,
  added when needed. If your deployment runs Gitea/Forgejo, swap the reference impl — port and
  config are unchanged.
- **Evidence-grounded verify (behavioural, assumed)**: the design **assumes** the verifier runs
  the modified project and exercises its real boundary — real HTTP requests for HTTP APIs
  (FastAPI-style), Playwright drive/visual inspection for web GUIs (Vite apps) — the two initial
  boundaries (FR-015b). The **exact behavioural harness (app launch, request/interaction
  scripting, browser automation, boundary detection) is out of scope for this feature** and may
  be delivered incrementally; **Playwright is an assumed future dependency, not added now**. v1
  ships the generic `Observation{kind}`/`Evidence` interface (T012), the verifier-as-adjudicator
  role + failing-observation invariant (T044/T047), and a minimal interim `check` gatherer (T017).
  Because the interface is generic, the HTTP/Playwright gatherer drops in later with no workflow
  reshape.
- `source`/`task_ref` are internal — never added to the API schema or `frontend/src/types/`, and
  never change which phases/gates a run traverses (FR-026; T053 pins this).
- Verify iterations + evidence are in-memory on the run's `_Control`; a restart mid-loop fails
  loudly like every transient state (T056) — no persisted counter (research R-06).
