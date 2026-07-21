---
description: "Task list for GitHub Ingestion & Repo Ops"
---

# Tasks: GitHub Ingestion & Repo Ops

**Input**: Design documents from `/specs/002-github-ingestion/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — Constitution III (Test-First Discipline, NON-NEGOTIABLE) makes
tests mandatory for every behaviour change. Write each story's tests first and see
them fail before implementing.

**Organization**: Grouped by user story. Priority order: P1 (US1 webhook + dismissal
lifecycle), P1 (US4 gate notifications), P2 (US2 reconciliation), P3 (US3 isolation).
US4 is the spec's "Gate notifications & deep-links (P1)" FR subsection, promoted to a
story for independent delivery.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4
- Backend tests are flat `backend/tests/test_*.py`; frontend tests live under
  `frontend/tests/<area>/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration surface the ingestion, reconciliation, and notification
work all read.

- [X] T001 Add ingestion settings to `backend/app/config.py`: `webhook_secret: str = ""`, `watched_repos: list[str] = []`, `trigger_label: str = "kestrel"`, `reconcile_interval_seconds: int = 300`, `public_base_url: str = ""`, plus a `model_validator` that warns when watched repos are set but `webhook_secret` is empty (env prefix `KESTREL_`)
- [X] T002 [P] Write config tests in `backend/tests/test_config.py`: `watched_repos` parses a comma/JSON list, defaults are correct, `public_base_url` unset ⇒ `""`
- [X] T003 [P] Document the new settings in `backend/.env.example` and `docs/configuration.md` (secret never committed)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema, model, and stores shared by US1 and US2. Must land before those
stories. (US3 and US4 depend only on Setup — see Dependencies.)

**⚠️ CRITICAL**: US1/US2 cannot start until this phase is complete.

- [X] T004 Add `source: str = "manual"` to `WorkflowRun` in `backend/app/models_workflow.py` (internal-only; not surfaced to the API/UI — clarification Q3)
- [X] T005 Add `WebhookDeliveryRow` (PK `delivery_id`, `event`, `outcome`, nullable `repo`/`issue_number`, `created_at`), `IssueDismissalRow` (composite PK `(repo, issue_number)`, `created_at`), and a `source` column (server_default `"manual"`) on `WorkflowRunRow` in `backend/app/persistence/tables.py`
- [X] T006 Create Alembic migration `backend/alembic/versions/0006_ingestion.py` (`down_revision = "0005"`): create `webhook_delivery` and `issue_dismissal`, add `workflow_run.source` with server default; `downgrade()` drops both tables and the column
- [X] T007 Persist and rehydrate `source` in `backend/app/persistence/workflow_store.py` (`save` upsert + `load_all` rebuild)
- [X] T008 [P] Extend `backend/tests/test_workflow_persistence.py` to assert `source` round-trips (default `"manual"`, explicit `"github-issue"`)
- [X] T009 Implement `WebhookDeliveryStore` (`seen(delivery_id, event, outcome, repo, issue_number)` atomic insert-if-absent returning prior presence; prune rows older than 7 days on insert) in `backend/app/persistence/webhook_delivery_store.py`
- [X] T010 [P] Write `backend/tests/test_webhook_delivery_store.py`: first `seen` ⇒ new, second ⇒ duplicate; prune drops rows past the retention window
- [X] T011 Implement `DismissalStore` (`add(repo, issue)`, `is_dismissed(repo, issue)`, `clear(repo, issue)`) in `backend/app/persistence/dismissal_store.py`
- [X] T012 [P] Write `backend/tests/test_dismissal_store.py`: `add` then `is_dismissed` ⇒ true; `clear` ⇒ false; idempotent add; survives a fresh store instance (durable)

**Checkpoint**: schema (`0006`), `source`, dedup store, and dismissal store exist and
are tested.

---

## Phase 3: User Story 1 - Auto-start a run when an issue is flagged (Priority: P1) 🎯 MVP

**Goal**: A signed `issues` `labeled` webhook for a watched repo's trigger label
starts exactly one run (indistinguishable from manual); abandoning a run dismisses
its issue so it is not re-ingested; `unlabeled` clears the dismissal.

**Independent Test**: Signed `labeled` ⇒ one run; resend ⇒ still one; bad/missing
signature ⇒ `401`, no run; abandon a still-labelled run ⇒ a `labeled` redelivery
starts nothing; `unlabeled` then `labeled` ⇒ a fresh run.

### Tests for User Story 1 (write first, ensure they fail)

- [X] T013 [P] [US1] Write webhook ingress tests in `backend/tests/test_webhook_ingress.py`: valid signature + trigger label + watched repo ⇒ `202` and one run; tampered/wrong/missing signature ⇒ `401`, zero runs; duplicate `X-GitHub-Delivery` ⇒ `200`, one run; non-trigger label / non-watched repo / non-`issues` event ⇒ `200`, zero runs; `labeled` on a **dismissed** issue ⇒ `200`, zero runs; `unlabeled` (trigger label) ⇒ dismissal cleared, later `labeled` starts a run
- [X] T014 [P] [US1] Write ingestion-service tests in `backend/tests/test_ingestion_service.py`: `maybe_start_run` starts one run for a watched repo; no-op for an unwatched repo; no-op for a dismissed `(repo,issue)`; never creates a second run for an existing `(repo,issue)`; run has `source="github-issue"`; a failing `create()` leaves **no** run record and **no** dismissal (FR-013a)
- [X] T015 [P] [US1] Write abandon-dismissal test in `backend/tests/test_workflow_service.py`: `delete()` records a dismissal for the run's `(repo,issue)`

### Implementation for User Story 1

- [X] T016 [US1] Implement `ingestion.maybe_start_run(repo, issue_number, *, source="github-issue")` (watched-repo check → dismissed-skip via `DismissalStore.is_dismissed` → one-run-per-`(repo,issue)` scan of `workflows.list()` → `WorkflowService.create(...)`, treating create as atomic so a failure leaves no run/dismissal) in `backend/app/services/ingestion.py`
- [X] T017 [US1] Extend `WorkflowService.create()` to accept and store `source` in `backend/app/services/workflows.py`
- [X] T018 [US1] Record a dismissal for `(repo, issue)` on abandon in `WorkflowService.delete()` in `backend/app/services/workflows.py`
- [X] T019 [US1] Implement the HMAC verification dependency (read raw body, `sha256` HMAC over `webhook_secret`, `hmac.compare_digest`; reject missing/invalid) in `backend/app/routers/github_webhook.py`
- [X] T020 [US1] Implement `POST /api/github/webhook`: on `labeled` → gate (event/label/watched) → dedup via `WebhookDeliveryStore.seen` → dismissed-skip → dispatch `maybe_start_run` as a background task and return `202` without blocking (FR-005); on `unlabeled` (trigger label) → `DismissalStore.clear`; record each delivery outcome + one structured log line, never logging the secret/signature (FR-006/FR-021) — in `backend/app/routers/github_webhook.py`
- [X] T021 [US1] Register the webhook router in `backend/app/main.py` (before the SPA static mount)

**Checkpoint**: MVP — labeling a watched issue autonomously starts one run; retries,
bad signatures, dismissal, and label-removal are handled. Ingested runs surface
exactly like manual ones.

---

## Phase 4: User Story 4 - Gate notifications & deep-links (Priority: P1)

**Goal**: Every `awaiting_*` gate posts a deterministic comment on the source issue
with a deep-link that opens the run's active gate form; best-effort, in-app
notification is the fallback.

**Independent Test**: Drive a run to `awaiting_refine_input` → a templated comment
with `Open in kestrel: {public}/?run=<id>` appears; clicking it opens that run's
questionnaire. Unset `public_base_url` → comment still posts, link-less. Restart at a
gate → no duplicate comment.

### Tests for User Story 4 (write first, ensure they fail)

- [X] T022 [P] [US4] Add `create_issue_comment` tests to `backend/tests/test_github_client.py`: posts `{"body": ...}` to `/repos/{repo}/issues/{n}/comments`, returns `html_url`, raises `GitHubError` on non-2xx without leaking the token (httpx mocked)
- [X] T023 [P] [US4] Write `backend/tests/test_github_notifier.py`: each `awaiting_*` status posts one comment with the templated body; `public_base_url` set ⇒ body ends with the deep-link, unset ⇒ no link; `create_issue_comment` raising is swallowed and logged; `done`/`failed`/`rejected` post nothing; `CompositeNotifier` still records the in-app row when the GitHub post fails
- [X] T024 [P] [US4] Add a restart-idempotency guard to `backend/tests/test_workflow_recovery.py`: recovering an `awaiting_*` run re-parks without invoking the notifier (no comment, no in-app row) — pins the R-07 invariant
- [X] T025 [P] [US4] Write a frontend deep-link test in `frontend/tests/composables/useWorkflows.deeplink.test.ts`: loading with `?run=<id>` calls `select('<id>')` once and shows the workflows view; no `run` param ⇒ no `select` call (HTTP/SSE mocked)

### Implementation for User Story 4

- [X] T026 [US4] Add `create_issue_comment(repo, number, body) -> str` to `backend/app/services/github.py`
- [X] T027 [US4] Add a deep-link builder (`{public_base_url}/?run={id}` when set, else empty) in `backend/app/notifications.py`
- [X] T028 [US4] Implement `GitHubIssueNotifier` (act only on `awaiting_*`; body = reused `render_message` + optional link line; POST fire-and-forget via `asyncio.create_task`, wrapped in try/except that logs and swallows — FR-026) in `backend/app/notifications.py`
- [X] T029 [US4] Implement `CompositeNotifier([...])` (InAppNotifier first, then GitHubIssueNotifier; a child error must not stop the others) in `backend/app/notifications.py`
- [X] T030 [US4] Wire the composite notifier in the `get_workflow_service()` factory in `backend/app/services/workflows.py` (replacing the bare `InAppNotifier`)
- [X] T031 [US4] Add the frontend deep-link entry: read `?run=<id>` on load in `frontend/src/main.ts` and call `useWorkflows().select(id)`, ensuring the workflows view is shown

**Checkpoint**: A maintainer not watching the UI is pinged on the issue at every gate
and lands directly on the right form; failures degrade to in-app only.

---

## Phase 5: User Story 2 - Catch up on missed deliveries (Priority: P2)

**Goal**: A periodic reconciliation loop starts runs for trigger-labelled issues the
webhook path never processed, idempotently with webhooks, and clears dismissals for
issues whose label was removed.

**Independent Test**: With the webhook path disabled, label a qualifying issue → one
run starts within a cycle; a second cycle starts no duplicate; a dismissed issue is
skipped, and once its label is removed the next cycle clears its dismissal; a GitHub
error is logged and the loop survives.

### Tests for User Story 2 (write first, ensure they fail)

- [X] T032 [US2] Add `list_issues_by_label` tests to `backend/tests/test_github_client.py`: unpaginates results, excludes pull requests (httpx mocked)
- [X] T033 [P] [US2] Write `backend/tests/test_reconcile.py`: a cycle starts exactly one run for an unhandled labelled issue; a second cycle starts none (idempotent via the guard); a dismissed issue is skipped; a dismissal for an issue no longer trigger-labelled is cleared; a GitHub failure is logged, starts no run, and the loop continues

### Implementation for User Story 2

- [X] T034 [US2] Add `list_issues_by_label(repo, label, *, state="open") -> list[Issue]` (paginated, PR-filtered) to `backend/app/services/github.py`
- [X] T035 [US2] Implement the reconciliation loop (every `reconcile_interval_seconds`, per watched repo: list by trigger label, funnel each issue through `ingestion.maybe_start_run`, and `DismissalStore.clear` any dismissal whose issue is no longer in the labelled set; wrap each cycle so a GitHub failure is logged and skipped — FR-014) in `backend/app/services/reconcile.py`
- [X] T036 [US2] Launch the reconcile task in `backend/app/main.py` `_lifespan` after `recover()` and before `yield` (run an initial cycle promptly so SC-002's bound holds), tracked in a module-level task set and cancelled on shutdown

**Checkpoint**: A delivery missed while offline still yields exactly one run,
independent of the webhook path; dismissals self-heal.

---

## Phase 6: User Story 3 - Isolate each run (Priority: P3)

**Goal**: Each run operates in its own `git worktree` off a per-repo shared bare
mirror; cleanup of one run never disturbs another, and done/failed runs no longer
leak their working copy.

**Independent Test**: Start two runs for the same repo at once → separate worktrees
and branches, neither sees the other's changes; abandon one → the other's worktree is
intact; a finished run pushes + opens a draft PR as before and its worktree is
cleaned up.

### Tests for User Story 3 (write first, ensure they fail)

- [X] T037 [P] [US3] Extend `backend/tests/test_git_service.py`: bare-mirror creation + `worktree add`/`remove`, two concurrent worktrees are isolated (independent index/branch), and the per-repo lock serialises worktree admin
- [X] T038 [P] [US3] Extend `backend/tests/test_workflow_service.py`: worktree is removed on done/failed/rejected and on abandon; a second in-flight run's worktree survives another's cleanup (FR-017)

### Implementation for User Story 3

- [X] T039 [US3] Add to `backend/app/services/git.py`: per-repo bare mirror clone + fetch, `worktree_add(dest, base_branch)` / `worktree_remove(dest)`, and a per-repo `asyncio.Lock` map guarding fetch + worktree add/remove
- [X] T040 [US3] Replace the per-run full clone with worktree provisioning in `WorkflowService._drive` (`backend/app/services/workflows.py`), keeping branch/push/draft-PR behaviour unchanged (FR-018)
- [X] T041 [US3] Remove the run's worktree on done, failed, and rejected (plus the existing abandon path), retaining the bare mirror, in `backend/app/services/workflows.py`

**Checkpoint**: Concurrent same-repo runs are safe and self-cleaning.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T042 [P] Update `docs/setup-github-workflow.md` with webhook setup (endpoint, secret, Issues events incl. `unlabeled`) and exposure guidance (tunnel/reverse proxy)
- [X] T043 [P] Update `docs/architecture.md`: note the single off-loopback webhook exception (~line 54, resolving the v1.2.0 constitution drift) and record the future-source seam — the `Notifier` outbound port, the `ingestion`/`source` inbound seam, and the Task-Source-vs-Code-Host axis (GitHub-only now; interfaces extracted with Jira) — so the boundary is deliberate
- [X] T044 Audit structured logging across `github_webhook.py`, `reconcile.py`, and `notifications.py` for delivery-outcome coverage (FR-021) and confirm no secret/token/signature is ever logged (FR-006/SC-007)
- [X] T045 Run the `quickstart.md` scenarios 1–6 end-to-end and record results
- [X] T046 Run full gates: `cd backend && uv run pytest`, `cd frontend && npm run test`, and linters/formatters with no suppressions

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup. **Blocks US1 and US2.**
- **US1 (Phase 3, P1)**: depends on Setup + Foundational. MVP.
- **US4 (Phase 4, P1)**: depends on Setup only (notifier + deep-link). Independent of
  US1's webhook, but most valuable *with* it.
- **US2 (Phase 5, P2)**: depends on Setup + Foundational **and reuses `ingestion.maybe_start_run` (T016) and `DismissalStore` (T011) from US1/Foundational**.
- **US3 (Phase 6, P3)**: depends on Setup only (git/workspace layer). Independent of US1/US2/US4.
- **Polish (Phase 7)**: after the stories it documents/validates are complete.

### Within each story

- Tests first (must fail before implementation).
- Models/schema before stores before services before routers/endpoints.
- `DismissalStore` (T011) before ingestion skip (T016), abandon-dismissal (T018), and reconcile-clear (T035).
- `ingestion.py` (T016) before the webhook handler (T020) and before reconcile (T035).

### Parallel opportunities

- Setup: T002, T003 in parallel.
- Foundational: T008, T010, T012 in parallel (different files); T004–T007/T009/T011 are ordering-sensitive within their own files.
- US1 tests: T013, T014, T015 in parallel (distinct files).
- US4 tests: T022, T023, T024, T025 all in parallel (distinct files).
- US3 tests: T037, T038 in parallel.
- Cross-story caution: US2 and US4 both edit `backend/app/services/github.py` and `backend/tests/test_github_client.py` (T026/T032, T022/T034), so they can't be fully parallelised despite dependency-independence — serialise those two files.

---

## Parallel Example: User Story 4

```bash
# Launch all US4 tests together (distinct files):
Task: "create_issue_comment tests in backend/tests/test_github_client.py"        # T022
Task: "GitHubIssueNotifier/CompositeNotifier tests in backend/tests/test_github_notifier.py"  # T023
Task: "restart-idempotency guard in backend/tests/test_workflow_recovery.py"     # T024
Task: "frontend deep-link test in frontend/tests/composables/useWorkflows.deeplink.test.ts"   # T025
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → Phase 2 Foundational → Phase 3 US1.
2. **STOP and validate**: signed label starts one run; dedup, bad-signature, and
   abandon-dismissal paths hold (quickstart Scenarios 1 & 6).
3. Shippable increment: autonomous run start with a safe abandon.

### Incremental delivery

1. Setup + Foundational → foundation ready.
2. US1 → autonomous start + dismissal (MVP).
3. US4 → gate pings + deep-links (the reason ingestion is usable unattended).
4. US2 → missed-delivery safety net + dismissal self-heal.
5. US3 → concurrency-safe isolation + leak fix.

Each story is independently testable; commit after each task or logical group.

---

## Notes

- [P] = different files, no incomplete dependency.
- Tests are mandatory (Constitution III); verify they fail before implementing.
- No new runtime dependency: HMAC uses stdlib `hmac`/`hashlib`; worktrees use the
  existing `git` subprocess helper.
- `source` is persisted-only and NOT surfaced to the API/UI (clarification Q3) — the
  earlier "expose source" tasks were removed.
- Restart idempotency for gate comments needs **no** new state — recovered gates
  re-park without `_save()` (research R-07); T024 pins this.
- A failed run-start leaves no run record and no dismissal, so reconciliation retries
  it (FR-013a); T014 asserts this.
- The constitution amendment (v1.2.0) recording the off-loopback webhook deviation is
  already done; T043 closes the matching `docs/architecture.md` drift.
