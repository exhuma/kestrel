# Tasks: Jira is where people work with kestrel (046)

**Input**: `specs/046-jira-first-alpha/` (spec, plan, research, data-model,
contracts, quickstart)

**Tests**: included, because constitution Principle III requires them. Each
story's tests are written first and fail before implementation.

**Paths**: backend paths are relative to `backend/`, frontend paths to
`frontend/`.

## Format: `[ID] [P?] [Story] Description`

`[P]` means the task can run in parallel: different files, no dependency on
an unfinished task.

---

## Phase 1: Setup

- [X] T001 Alembic migration `alembic/versions/0036_jira_channel.py`:
  - add `task_ref`, `payload`, `attempts` to `board_external_projection`;
  - create `board_comment_cursor` and `board_inbound_comment` (data-model.md);
  - leave the `board_workflow` document-column conversion for T013.
- [X] T002 [P] Config in `app/config.py`, `app/config_models.py` and
  `config.toml.example`:
  - add `change_owner_field: str = ""` to the Jira `TaskSourceConfig`;
  - add `board_comment_poll_interval_seconds` (60) and
    `board_projection_retry_interval_seconds` (120) to `Settings` and to
    `_CONFIG_FILE_FIELDS`;
  - keep `feedback_marker` (`@kestrel`) and document it as the reply marker;
  - delete `feedback_ignore_authors` and `feedback_window_days`;
  - tests in `tests/test_config.py`.
  - *Done (track 01):* the configurable `comment_sentinel` text was removed
    (the marker's look is now each adapter's); `comment_sentinel_enabled` stays.

---

## Phase 2: Foundational

**Document constructs and format modules.** Every story depends on these.

- [X] T003 [P] Tests in `tests/test_documents.py` for the new constructs and
  their validation: `Mention`, `HardBreak`, `Image`, `Table` (rectangular),
  `Marker`, nested `ListItem` lists, and the derived queries `markers()`,
  `plain_text()`, `mentions()`.
- [X] T004 Extend `app/documents.py` with those constructs and derived
  queries. Remove every parser and renderer from the module, so it holds
  constructs and validating builders only.
- [X] T005 [P] Tests in `tests/test_document_formats_markdown.py` for the
  Markdown format:
  - tables, images, hard breaks, nested lists, blockquote and nested marks
    parse as research R1 says;
  - parsed documents are validated;
  - `OrderedList.start` survives;
  - render ∘ parse is stable.
- [X] T006 Create `app/document_formats/markdown.py` (commonmark preset plus
  the table rule, list nesting and breaks fixed) and
  `app/document_formats/text.py`. Move the code out of
  `app/documents_parser.py` and delete that file.
- [X] T007 [P] Tests in `tests/test_document_formats_adf.py`:
  - every row of `contracts/adf-mapping.md`, in both directions;
  - a round-trip property, `parse_adf(render_adf(d)) == d`, over generated
    documents from the closed set;
  - unknown ADF nodes degrade to their text without raising.
  - *Done (track 01):* the round-trip runs over an exhaustive hand-built set
    covering every construct instead of generated documents, to avoid adding
    a property-testing dependency (Principle IV).
- [X] T008 Create `app/document_formats/adf.py` with `render_adf` (moved
  from `documents.py`, now emitting `order`, tables, mentions, hard breaks
  and `Marker`) and the new `parse_adf`, as `contracts/adf-mapping.md`
  specifies.
- [X] T009 [P] Move `app/documents_json.py` to `app/document_formats/json.py`,
  extend it to the new constructs, and add round-trip tests in
  `tests/test_document_formats_json.py`.
- [X] T010 Add the import-linter contract
  `[importlinter:contract:documents-at-the-boundary]` to `.importlinter`:
  - type `forbidden`;
  - sources `app.services.board`, `app.routers`, `app.models_board`,
    `app.persistence`;
  - forbidden module `app.document_formats`;
  - allowed importers listed in the contract comment, as plan.md says.

**Ports and adapters.**

- [X] T011 Change the ports in `app/ports.py` as `contracts/ports.md` says:
  - add `Person`;
  - `Task.body` becomes `Document`, and `Task` gains `reporter` and
    `change_owner`;
  - `Feedback.author` becomes `Person` and `Feedback.body` becomes
    `Document`;
  - `list_comments` returns `CommentPage`;
  - remove every `Document | str`;
  - document `transition()` as sub-tasks only.
- [X] T012 Update the adapters to the new port types: `app/services/jira.py`,
  `app/services/jira_document.py`, `app/services/github_tasksource.py`,
  `app/services/github.py`, `app/services/gitlab.py`,
  `app/services/local_task_source.py`, `app/services/github_reviews.py`.
  - Jira:
    - render ADF directly, with no Markdown round-trip;
    - post the sentinel as `Marker("posted")`;
    - parse descriptions and comments with `parse_adf`, replacing `to_text`;
    - request `reporter` and `change_owner_field`, reading `accountId` and
      `displayName`;
    - read comment authors by `accountId`.
  - GitHub and local:
    - the sentinel becomes a `Marker` rendered as their HTML comment;
    - `reporter` is the issue author.
  - Tests: extend `tests/test_jira_client.py` and `tests/test_jira_document.py`
    (replace the `to_text` cases with `parse_adf` ones), plus the existing
    GitHub, GitLab and local adapter tests.
  - *Done (track 01):* the Jira REST client moved to `app/services/jira_client.py`
    (`jira.py` was at the 500-line limit); `jira_document.py` and `markers.py`
    are deleted. A comment author without an account keeps only their name,
    with an empty `account_id` that must never match anyone (US3).

**Persistence and the agent boundary.**

- [X] T013 Persistence as a boundary:
  - new `app/persistence/document_column.py`, a SQLAlchemy type that maps
    `Document` to document JSON;
  - in migration 0036, convert `board_workflow.task_body` and
    `approved_prd` by parsing the stored Markdown once;
  - in `app/models_board.py`, type `Workflow.task_body` and `approved_prd`
    as `Document`;
  - in `app/persistence/board_store.py`, update `record_intake` and
    `record_approved_prd`;
  - tests in `tests/test_board_store.py`.
  - *Done (track 01):* no data conversion in migration 0036. The column type
    parses a legacy Markdown value when read, so old rows need no migration
    and the migration imports no app code. Tests for T013 and T014 are in
    `tests/test_document_persistence.py`.
- [X] T014 Document artifacts:
  - in `app/services/board/artifacts.py`, add mime type
    `application/vnd.kestrel.document+json` and
    `store_document_artifact(...)` / `read_document(...)`;
  - legacy `text/markdown` artifacts are parsed on read in the persistence
    layer;
  - tests in `tests/test_board_artifacts.py`.
- [X] T015 The agent-result boundary:
  - parse agent Markdown into a `Document` when results are accepted, in
    `app/services/board/understanding.py` (restatement),
    `app/services/board/refinement.py` (PRD draft) and
    `app/services/board/dispatch_ready.py`;
  - rebuild `app/services/board/exec_summary.py`, `render_breakdown` in
    `app/services/board/materialise.py` and `pr_body` in
    `app/services/board/delivery_body.py` from constructs (`Table`,
    `Image`, lists) with no Markdown strings;
  - update `tests/test_board_exec_summary.py` and
    `tests/test_board_delivery_body.py`.
  - *Done (track 01), one gap left:* gate `response` artifacts (human answers
    in the machine-parsed `Q:`/`A:` format) are still plain text. Not in the
    constitution's list of named violations; a follow-up if they need rich
    content.
- [X] T016 Rendering at the outer boundaries:
  - `app/services/board/dispatch.py` (`build_card_envelope`) renders
    documents to Markdown for prompts;
  - API serialisers in `app/routers/board_views.py` and `app/routers/board.py`
    render documents to Markdown;
  - response shapes in `app/schemas.py` stay unchanged (Principle I), and a
    test in `tests/test_board_router_views.py` asserts it.

**Checkpoint:** `task quality` passes, including the new contract, and no
Principle VI violation named in the constitution remains.

---

## Phase 3: User Story 1, everything kestrel posts reads properly in Jira (P1) 🎯 MVP

**Goal:** comments render natively, mentions notify, and inbound structure
survives.

**Independent test:** with a recording fake Jira client, posting a document
that uses every construct produces the expected ADF, and reading ADF back
gives the same document.

- [X] T017 [P] [US1] Test in `tests/test_jira_comment_rendering.py`:
  - `JiraTaskSource.post_comment` sends exactly `render_adf(document +
    Marker("posted"))`;
  - it never calls a Markdown renderer;
  - a `Mention` becomes an ADF `mention` node with the account ID.
  - *Done (track 01):* the tests live in `tests/test_jira_document.py`.
- [X] T018 [P] [US1] Test in `tests/test_jira_ingest_structure.py`: an issue
  description with a heading, a nested list, a table and a link reaches
  `Workflow.task_body` and the API's "original request" with its structure
  intact.
- [X] T019 [US1] Fix whatever T017 and T018 expose in
  `app/services/jira.py` and `app/services/ingestion.py`. Screening
  receives the document rendered to plain text (`text` format) at the
  quarantine boundary in `app/services/board/quarantine.py`.
  - *Done (track 01):* the quarantine service is the screening boundary and
    renders the document itself; the screened text now includes link targets.
    Covered by `tests/test_jira_ingest_structure.py`, together with T018.

**Checkpoint:** Story 1 is independently demonstrable (quickstart step 1).

---

## Phase 4: User Story 2, the ticket says what is needed, from whom (P1)

**Goal:** one comment per gate opening, with the right people mentioned,
change-owner "should move on" notices, retried posts, and no status change.

**Independent test:** drive a request through every gate with a fake Jira
source. Assert one comment per opening with the expected mentions, no
`transition()` call, and no CAB mention.

**Tests first.**

- [ ] T020 [P] [US2] Tests in `tests/test_board_gate_opened.py`:
  `GatesService.create_gate` appends a `gate.opened` event and bumps the
  workflow revision, for each of the six call sites.
- [ ] T021 [P] [US2] Tests in `tests/test_board_announcements.py`, one per
  row of data-model.md's announcement table:
  - document content;
  - mentions: the reporter on requester gates, the change owner on CAB
    gates and "should move on" notices, nobody otherwise;
  - idempotency key, the kestrel link (omitted when `public_base_url` is
    unset), and the trailing `Marker`;
  - the "no change owner set" variant;
  - one comment per refinement batch.
- [ ] T022 [P] [US2] Tests in `tests/test_board_projection_retry.py`:
  - a failed post is stored with its payload and `task_ref`;
  - the retry loop re-posts it once it succeeds, with backoff by `attempts`;
  - restarts never post twice.
- [ ] T023 [P] [US2] Test in `tests/test_board_no_transition.py`: across a
  full request, `TaskSource.transition` is never called for the ingested
  issue (constitution, fourth access-model constraint).

**Implementation.**

- [ ] T024 [US2] Route `GatesService.create_gate` in
  `app/services/board/gates.py` through `BoardService`, so it appends a
  `gate.opened` event with `{"gate_kind": ...}` and bumps the revision.
- [ ] T025 [US2] Ledger keeps its payload (`ProjectionRequest.payload` is
  already a `Document` since track 01; what remains is storing it):
  - `app/persistence/board_projection_store.py` stores `task_ref`,
    `payload` (document JSON through `app/document_formats/json.py`) and
    `attempts`, and can re-arm `retryable_failure` rows;
  - `app/services/board/projections.py` adds the kinds `gate_opened`,
    `status` and `reply`;
  - `ProjectionRequest.payload` in `app/services/board/write_back.py`
    becomes a `Document`.
- [ ] T026 [P] [US2] Builders in `app/services/board/announcements/`, one
  module per family, each returning a `Document` built from constructs:
  - `gates.py`: understanding, strategic interview, refinement batch, PRD,
    CAB-1, CAB-2;
  - `status.py`: delivered, failed, cancelled, CI failed or repaired,
    escalation;
  - `common.py`: the kestrel link, how-to-answer text, mentions.
- [ ] T027 [US2] `app/services/board/announcements/service.py`:
  `AnnouncementService` subscribes to board mutations, the way
  `_trigger_scheduling` does in `app/services/board/bootstrap.py`. It:
  - maps events to builders;
  - resolves the reporter and change owner by fetching the `Task` through
    the workflow's source;
  - plans and posts through the ledger.

  It detects failed and cancelled outcomes with feature 040's outcome
  derivation, and CI status changes from `app/services/board/ci_poll.py`.
- [ ] T028 [US2] Move the existing projections onto Documents and the
  announcement service: in `app/services/board/bootstrap.py`,
  `_project_gate`, `_project_escalation`, `_project_breakdown` and
  `_project_prd_approval`; plus `app/services/board/dispatch_delivery.py`
  and `app/services/board/dispatch_ready.py`. The delivered comment
  mentions the change owner.
- [ ] T029 [US2] `app/services/board/projection_retry.py`:
  `ProjectionRetryService.run_forever` / `poll_once`, wrapped in try/except
  per cycle. Wire it in `bootstrap.py` (`get_projection_retry_service`) and
  start it in `app/main.py` next to the CI loop.
- [ ] T030 [P] [US2] Docs: `docs/setup-jira-workflow.md` (change-owner
  field, what the ticket shows, no status changes, no CAB mentions) and
  `docs/configuration.md` (new settings).

**Checkpoint:** quickstart steps 2 and 3 pass, and the alpha is usable with
UI answers.

---

## Phase 5: User Story 3, a reply on the ticket decides (P2)

**Goal:** `@kestrel` replies from the entitled person resolve gates exactly
as the UI does, with attribution and confirmation.

**Independent test:** with a gate open, a fake comment page with replies
from the reporter, the change owner and a stranger leads to exactly the
expected decision, refusal, question back and confirmations.

**Tests first.**

- [ ] T031 [P] [US3] Tests in `tests/test_board_comment_filter.py`:
  - a comment counts only with the `feedback_marker` as a whole word,
    ignoring case;
  - a comment carrying `Marker("posted")` is skipped even though it
    contains `@kestrel`, because kestrel's own announcements do;
  - the operator's own unmarked reply is considered.
- [ ] T032 [P] [US3] Tests in `tests/test_board_reply_entitlement.py`:
  - the reporter decides requester gates; the change owner decides CAB-1
    and CAB-2;
  - anyone else is refused;
  - interview gates get the pointer, and "nothing open" gets `no_gate`;
  - the reporter and change owner are re-read when the comment is
    processed.
- [ ] T033 [P] [US3] Tests in `tests/test_board_liaison.py`: the envelope
  matches `contracts/liaison-turn.md`, and malformed output, a timeout, a
  backend error, or a reasonless rejection where a reason is needed all
  give `unclear`.
- [ ] T034 [P] [US3] Tests in `tests/test_board_gate_reasons.py`:
  `GatesService.resolve` rejects a `confirm_understanding` or `approve_prd`
  rejection without `answer`, and writes `decided_by` into the
  `gate.approved` / `gate.rejected` payload.
- [ ] T035 [P] [US3] Tests in `tests/test_board_comment_poll.py`:
  - the cursor advances;
  - each external ID is processed at most once, across restarts and edits;
  - several replies are taken in order, with "first decides, rest are
    already decided";
  - a gate decided in the UI first gives "already decided" with who
    decided;
  - a held comment decides nothing; after release it is re-processed and
    decides; after a discard the ticket is told.

**Implementation.**

- [ ] T036 [US3] `app/persistence/comment_store.py`: the cursor and
  inbound-comment store (`get_cursor`, `set_cursor`, `claim(external_id)`
  insert-if-absent, `record_outcome`, `held_for_review(review_id)`), with
  `@lru_cache get_comment_store()`.
- [ ] T037 [US3] Backend reason rule and attribution:
  - in `app/services/board/gates.py`, `resolve(..., decided_by: Decider |
    None)` enforces the reason rule and passes an event payload;
  - in `app/services/board/service.py`, `transition_card` accepts a
    payload;
  - `app/services/board/interventions.py` passes `decided_by=None` (the UI
    operator);
  - `app/routers/board.py` maps the new error to HTTP 422.
- [ ] T038 [US3] The liaison specialist:
  - `specialists/liaison/manifest.toml`: no workspace, no card types;
  - `specialists/liaison/prompt.md`;
  - `app/services/board/liaison.py`: envelope (rendering at the agent
    boundary), a direct turn modelled on `dispatch.classify_input`, a
    fail-closed parser.
- [ ] T039 [US3] `app/services/board/replies.py`:
  - the filter (marker word, own `Marker`);
  - matching the open Jira-facing gate (understanding, strategic interview,
    PRD, CAB-1, CAB-2);
  - entitlement;
  - screening via `QuarantineService.intake_for_existing_workflow` with
    `category=f"gate-reply:{comment_id}"`;
  - liaison interpretation;
  - `GatesService.resolve` with `Decider(channel="jira", ...)`;
  - planning a `reply:{external_id}` announcement through
    `announcements/replies.py` for confirmation, refusal, question, hold,
    already decided, interview pointer or no gate.
- [ ] T040 [US3] `app/services/board/comment_poll.py`:
  `CommentPollService.run_forever` / `poll_once` over active workflows
  whose source supports `list_comments`, in created order, with try/except
  per workflow. Wire it in `bootstrap.py` (`get_comment_poll_service`) and
  start it in `app/main.py`.
- [ ] T041 [US3] Release continuation: in `app/routers/board.py`
  (security-review resolve), when the review's source identity has the
  `gate-reply:` category, schedule re-processing of that one comment
  through `replies.py` (re-fetch by ID). On a discard, plan the "held, not
  acted on" reply.
- [ ] T042 [P] [US3] Frontend attribution:
  - `frontend/src/lib/personas.ts` and `frontend/src/types/` show "<name>
    decided via Jira" when the gate event payload has a `channel`;
  - tests in `frontend/tests/lib/personas.test.ts`;
  - the backend payload test in the same commit (Principle I).
- [ ] T043 [US3] End-to-end test in `tests/test_board_jira_channel_e2e.py`:
  a fake Jira source carries one request from intake to delivery using only
  comments (interviews answered through the existing UI path). It asserts
  SC-001 to SC-005: one comment per gate, at most once, no CAB mention, no
  transition, strangers never decide.

**Checkpoint:** quickstart steps 4 and 5 pass.

---

## Phase 6: Polish

- [X] T044 [P] Delete the dead `app/review_requests.py` and its test, and
  remove `ReviewTokenMarker` from `app/markers.py` if nothing else uses it
  (#65 asked for a decision: the durable comment mapping replaces it).
  - *Done early (track 01):* deleted with the rest of the string-marker code.
- [ ] T045 [P] Update `docs/architecture.md` (the document boundary, the
  announcement and reply flow) and `docs/feedback-intake.md` (now ticket
  replies through 046).
- [ ] T046 Run `task quality`, prettier, the frontend build, pytest and
  vitest (pre-push checks).
- [ ] T047 Run `quickstart.md` against Jira Cloud. Record the results in
  `specs/046-jira-first-alpha/quickstart.md`, then close #65 with a link
  to the commits.

---

## Dependencies & execution order

- **Setup (T001–T002)** comes first.
- **Foundational (T003–T016)** blocks all stories.
  - T004 → T006 / T008 / T009 → T010.
  - T011 → T012.
  - T013 needs T009 and T001.
  - T014–T016 need T013.
- **US1 (T017–T019)** needs only Foundational. It is the MVP.
- **US2 (T020–T030)** needs Foundational. It is independent of US1's tests,
  but uses the same adapter.
- **US3 (T031–T043)** needs US2's ledger (T025) and builders (T026) for its
  confirmations, and T024 for gate events.
- **Polish** comes last.

Within a story: tests before implementation, the store before the
services, the services before wiring them into `main.py`.

## Parallel opportunities

- Foundational: the tests T003, T005, T007 and T009 can run together. T006,
  T008 and T009 can run together once T004 is in.
- US2: the tests T020–T023 can run together, then T026 and T030 in
  parallel with T024 and T025.
- US3: the tests T031–T035 can run together. T038 and T042 are parallel to
  T036 and T037.
- Parallelism is limited: `gates.py`, `bootstrap.py` and `main.py` are
  shared by T024, T027, T029, T037 and T040. Don't split those across
  agents.

## Implementation strategy

1. **MVP is Foundational + US1.** It also pays off the Principle VI debt.
   Ship and verify rendering against Jira Cloud.
2. **Then US2.** The alpha becomes usable, with people reading the ticket
   and answering in the UI. This is a good point for testers to start.
3. **Then US3.** Jira becomes the main channel.
4. Commit each phase separately, so they stay separable in history.
