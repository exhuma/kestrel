# Research: Jira is where people work with kestrel (046)

Findings come from reading the code at `0b98f8d`. Paths are relative to
`backend/app/` unless stated otherwise.

## R1. The Document model is too small for what kestrel must post

**Found.** `documents.py` has five inlines (`Text`, `Strong`, `Emphasis`,
`Code`, `Link`) and six blocks (`Heading`, `Paragraph`, `CodeBlock`,
`BulletList`, `OrderedList`, `Rule`). It has no table, mention, image, hard
break, or nested list. `ListItem` holds paragraphs only. `render_adf` drops
`OrderedList.start`. `parse_markdown` uses markdown-it's commonmark preset,
which means:

- a table becomes one paragraph of pipe characters;
- images vanish, alt text included;
- line breaks vanish (`a\nb` renders as `ab`);
- a nested list breaks out of its parent;
- only the innermost mark survives.

The CAB-2 executive summary has a Tasks table. The PR body has screenshots.

**Decision.** Extend the closed set:

- `Mention(account_id, display_name)` (inline);
- `HardBreak` (inline);
- `Image(src, alt)` (block);
- `Table(header, rows)`, where cells are inline content (block);
- `Marker(name)` for kestrel's ownership and correlation markers (block);
- `ListItem` may hold nested lists;
- `OrderedList.start` is rendered.

Switch the Markdown parser to commonmark plus the table rule, and fix list
nesting and line breaks.

**Alternatives.** Post the executive summary as a code block (unreadable). A
Jira-only escape hatch that carries raw ADF (Principle VI forbids it).

## R2. Where parsing and rendering live, and how to enforce it

**Found.** The model and every parser and renderer share one module, so any
importer of a construct can also call `parse_markdown` or `render_adf`. No
`services/board/*` module imports `app.documents` today. `documents_json.py`
round-trips the model but has no callers. import-linter is configured in
`backend/.importlinter`, with three contracts.

**Decision.** Split the module:

- `app/documents.py` keeps the constructs and validating builders, pure,
  with no format knowledge.
- A new package, `app/document_formats/`, holds one module per format:
  `markdown`, `adf`, `text`, `json`. Each has `parse_*` and `render_*`.

Add a `forbidden` contract: `app.services.board`, `app.routers`,
`app.models_board` and `app.persistence` may not import
`app.document_formats`. Allowed importers are listed explicitly: the
task-source and code-host adapters, the agent-result boundary, the document
column type, and the API schema serialisers.

**Alternatives.** A naming convention (not mechanical). A runtime check
(too late).

## R3. Jira in and out

**Found.**

- **Outbound:** `JiraTaskSource.post_comment` goes str → Document →
  Markdown + `[kestrel:posted]` → Document → ADF. That is a round trip.
- **Inbound:** issue descriptions and comments are flattened by
  `jira_document.to_text`, which loses marks, mentions, tables and breaks.
  There is no ADF → Document parser.
- **Fields:** `get_issue` requests only `summary,description`. `get_field`
  stringifies dict-valued fields.
- **Comment authors:** read as `displayName`. Cloud also returns `accountId`,
  which is discarded.

**Decision.**

- `document_formats.adf.parse_adf` handles: paragraph, heading, nested
  bullet/ordered lists, codeBlock, rule, table, mention, hardBreak, media
  (as `Image` where a URL is resolvable, otherwise its alt text), and the
  marks strong/em/code/link. Unknown container nodes (panel, expand,
  blockquote) keep their children. Unknown leaf nodes keep their text.
- Outbound renders the given Document straight to ADF. The sentinel becomes
  a `Marker("posted")` block, rendered by Jira as a small code-marked
  paragraph, because Cloud drops HTML comments.
- `get_issue` and search request `reporter` and the configured change-owner
  field, and read each one's `accountId` and `displayName`.

**Alternatives.** Keep `to_text` and parse mentions with a regex. Plain
text has already lost the mention nodes, so this cannot work.

## R4. Port types

**Decision.**

- `TaskSource` and `CodeHost` methods take `Document`, never `Document | str`.
- `Task.body` and `Feedback.body` become `Document`.
- New value type `Person(account_id, display_name)`.
- `Task` gains `reporter: Person | None` and `change_owner: Person | None`.
  GitHub and the local source set `reporter` (the issue author or file
  owner) and leave `change_owner` at `None`.
- `Feedback` gains `author: Person` (replacing `author: str`).
- No self-identity port method: without a service account, kestrel's
  author is the operator's (see R8).

## R5. Persistence and the agent boundary

**Found.**

- `Workflow.task_body` and `approved_prd` are `Text` columns holding
  Markdown.
- Artifacts are `str` with a `mime_type`. Restatement, PRD draft, executive
  summary and task spec are `text/markdown`.
- The API returns artifact content as a raw string. The frontend renders it
  with its own markdown-it (default preset, so tables are on).

**Decision.** Persistence is a boundary (Principle VI). It stores document
JSON:

- New artifacts that are documents get mime type
  `application/vnd.kestrel.document+json`.
- `task_body` and `approved_prd` are migrated to document JSON (Alembic
  0036 parses the existing Markdown once).
- The agent-result boundary (`dispatch_ready` accepting a result) parses an
  agent's Markdown into a Document. So do the restatement, PRD and
  executive-summary routes. The executive summary is built from constructs
  directly (`exec_summary.py`), with no Markdown at all.
- The HTTP API renders Documents to Markdown for the frontend. That is an
  API-boundary adapter, which keeps the frontend's renderer and its type
  contract unchanged.
- Prompts render Documents to Markdown in the agent-backend adapter
  (`dispatch.build_card_envelope`).
- Legacy `text/markdown` artifacts already stored are parsed on read by the
  persistence boundary. No backfill.

**Alternatives.** Keep storing Markdown and parse wherever a Document is
needed. That moves parsing into core code and repeats it.

## R6. Announcing gates

**Found.** `GatesService.create_gate` writes the card and the gate record
straight to the stores. It appends no event, bumps no revision, and fires
no hook. Six call sites open six gate kinds:

| Gate | Opened in |
| --- | --- |
| understanding | `understanding.py:60` |
| refinement | `question_review.py:249` |
| strategic interview | `refinement.py:162` |
| PRD | `refinement.py:204` |
| CAB-1 | `gates.py:357` |
| CAB-2 | `estimation.py:203` |

Projections exist only after resolution.

**Decision.**

- `create_gate` goes through `BoardService` and appends a `gate.opened`
  event. This also fixes the missing revision bump the UI relies on.
- A new `AnnouncementService` subscribes to board events, like
  `_trigger_scheduling`, and maps event types to announcements (table in
  `data-model.md`).
- Each announcement is a Document built from constructs by a per-kind
  builder in `services/board/announcements/`. It is posted through the
  projection ledger.
- Refinement gates open in batches (feature 038): one comment per batch,
  keyed by the batch's interview plan.

## R7. The projection ledger cannot retry

**Found.** The ledger stores only `payload_hash`. `post_projection` posts
only `pending` rows. `retryable()` and `list_retryable()` have no callers. A
failed post is lost for good.

**Decision.**

- Store the payload as document JSON (new column `payload`, Alembic 0036),
  plus the target `task_ref`.
- A `ProjectionRetryService` loop re-posts `retryable_failure` rows with
  backoff, at most once each, keyed by the existing idempotency key.
- New kinds: `gate_opened`, `status`, `reply`.

## R8. Reading replies

**Decision.**

- **The loop.** `CommentPollService` (new loop in `main.py`, interval
  `board_comment_poll_interval_seconds`, default 60) reads comments on the
  tickets of active workflows whose source has a Jira-type adapter.
- **Read position.** A per-workflow cursor table records where it got to.
  Jira's `since` filter is inclusive, so a processed-comment table keyed by
  `Feedback.external_id` makes "at most once" hold.
- **Filter.**
  1. **Kestrel's own comments are skipped by their `Marker("posted")`.**
     There is no service account yet, so kestrel posts as the operator:
     author identity cannot tell kestrel's comments from the operator's
     real replies, but the marker can. The operator's replies carry no
     marker and are treated like anyone else's.
  2. **Only comments containing the plain-text marker are considered**:
     `feedback_marker` (default `@kestrel`, revived from feature 013),
     matched case-insensitively as a whole word in the comment's
     `plain_text()`. On Jira Cloud, `@kestrel` typed without a matching
     user stays plain text.
  3. Kestrel's own announcements tell people to reply with `@kestrel`, so
     they contain the marker text. Rule 1 is what keeps kestrel from
     answering itself; a test pins it.
  - Later, with a service account: author-based skipping and an exact
    mention match replace both rules. This is a change inside the Jira
    adapter and this filter only.
- **Edits.** An edited comment keeps its external ID, so it is never
  reprocessed (spec edge case).

## R9. Who may decide

**Decision.** Fetch the issue fresh when a comment is processed, so a
changed reporter or change owner is respected. Then:

- requester gates (understanding, strategic interview, PRD): only
  `reporter.account_id`;
- CAB-1 and CAB-2: only `change_owner.account_id`;
- anyone else: refused, with a reply.

Interview (refinement) gates are never decided from the ticket. A reply
gets a pointer to the form.

## R10. Screening replies

**Found.** `intake_for_existing_workflow` derives its identity from
`workflow.id:category` and dedups by content hash, so two identical comments
would collide. On release, the router continues *task intake* only
(`schedule_intake_continuation`), and the review record does not carry the
category.

**Decision.**

- Screen with `category=f"gate-reply:{comment_id}"`, so each comment has
  its own identity.
- A held comment is recorded as `held` in the processed-comment table, with
  its security-review ID.
- On release, the router also branches on that category prefix and
  schedules re-processing of that one comment: it is re-fetched by ID, and
  re-screening passes because the hash was released.

## R11. Understanding what a reply means

**Found.** The only no-tools enum classification is input-security's
`classify_input`.

**Decision.**

- Add a specialist, **liaison** ("the colleague who reads the ticket"),
  with no workspace and no card types. It is invoked directly, like
  input-security.
- Its envelope gives: the gate kind and what was asked, the reply as
  `<UNTRUSTED_CONTENT>` (rendered to Markdown at the agent boundary), and
  whether a reason is needed.
- It answers `<REPLY>{"intent": "approve"|"reject"|"unclear", "reason":
  "..."}</REPLY>`.
- **Fail closed:** malformed output, a timeout, or a backend error all mean
  `unclear`, which leads to a question back and never a decision.

## R12. Reasons and attribution

**Found.**

- "A rejection needs a reason" is enforced only in the frontend
  (`frontend/src/lib/asks.ts:51`), for `approve_prd` and
  `confirm_understanding`.
- Gate events carry `payload="{}"`, and `transition_card` cannot take a
  payload.
- The feed labels every `gate.*` event "You".

**Decision.**

- Move the reason rule into `GatesService.resolve` (Principle II). The
  frontend check stays as UX.
- `resolve` takes `decided_by: Decider | None`, written into the event
  payload as `{"detail": "...", "channel": "jira", "account_id": "...",
  "display_name": "..."}`.
- The frontend feed shows the display name instead of "You" when a
  `channel` is present. This is a small `personas.ts` change.

## R13. Constitution

**Already satisfied:**

- Principle VI is implemented by R1–R5.
- The fourth access-model constraint holds: nothing calls `transition` on
  the ingested issue.
- Polling adds no network exposure.

**Known gap, deferred (decided 2026-10-05):** Principle IV is not
amended. Kestrel stays single-user; the reporter and change owner deciding
from the ticket is an accepted gap for the alpha, to be settled with the
access & identity epic (#81). Nothing in this feature adds kestrel-side
authentication or users. Spec 013 FR-006 is superseded for the ticket
channel only.
