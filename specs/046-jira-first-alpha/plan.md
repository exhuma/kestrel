# Implementation Plan: Jira is where people work with kestrel

**Branch**: `work` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/046-jira-first-alpha/spec.md`

## Summary

Make the Jira ticket the main channel for a request's reporter and change
owner. There are three slices, in dependency order:

1. **Faithful documents (Story 1).** Bring the `Document` model up to
   constitution Principle VI:
   - add the missing constructs (mention, table, image, hard break, nested
     lists, marker);
   - split parsing and rendering into per-format adapter modules, guarded
     by an import-linter contract;
   - add an ADF parser;
   - type the ports as `Document` and `Person`;
   - store documents as JSON at the persistence boundary.
2. **Announcements (Story 2).** Gates emit a `gate.opened` event. An
   announcement service turns board events into Documents, which are posted
   through the projection ledger. The ledger now keeps its payload, so a
   retry loop can re-post failed comments.
3. **Replies (Story 3).** A comment poller reads comments containing the
   plain-text `@kestrel` marker on the tickets of active requests, skipping
   kestrel's own (recognised by their ownership marker, since kestrel posts
   as the operator until a service account exists). Each comment is:
   - checked against the person entitled to the open gate;
   - screened by input security;
   - interpreted by a new no-tools `liaison` specialist;
   - applied through the same `GatesService.resolve` the UI uses, now with
     attribution.

Research and decisions are in [research.md](research.md), entities and
tables in [data-model.md](data-model.md), interfaces in
[contracts/](contracts/), and validation in [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript / Vue 3 (frontend:
feed attribution only)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 + Alembic, markdown-it-py
(table rule enabled), httpx (Jira REST v3). No new dependency.

**Storage**: SQLite, with Alembic 0036:
- `board_workflow` document columns;
- new ledger columns;
- `board_comment_cursor`;
- `board_inbound_comment`.

**Testing**: pytest (with a property test for the ADF round-trip) and
vitest. A fake Jira adapter drives the end-to-end test. No live Jira in CI.

**Target Platform**: Linux server or container, Jira Cloud.

**Project Type**: Web service with an SPA.

**Performance Goals**: A reply is acted on within one comment-poll interval
(default 60 s). A failed post is retried within one retry interval
(default 120 s).

**Constraints**:
- At most once per comment and per announcement, across restarts.
- Fail closed on screening and interpretation.
- No status change on an ingested issue.
- No CAB mention.

**Scale/Scope**: Alpha with a handful of users and tens of active requests.
Polling cost is one comment listing per active Jira request per interval.

## Constitution Check

*Gate before Phase 0; re-checked after Phase 1.*

| Principle / constraint | Status |
| --- | --- |
| I. Contract fidelity | ✅ API shapes unchanged: documents are rendered to Markdown at the API boundary. The feed's event payload gains attribution fields; `frontend/src/types` and `personas.ts` change in the same commit as the backend. |
| II. Backend-owned | ✅ The "rejection needs a reason" rule moves from the frontend into `GatesService.resolve`. |
| III. Test-first | ✅ Every slice ships with tests. The ADF mapping has a round-trip property test. |
| IV. Single-user scope | ⚠️ **Known gap, accepted and deferred** (decision 2026-10-05). Kestrel stays single-user: no kestrel-side users or auth are added. The reporter and change owner deciding from the ticket is recorded in Complexity Tracking and left for the access & identity epic (#81). Not a blocker. |
| V. Kit-aligned, observable | ✅ Structured logs per poll and post. Failed posts remain visible in the ledger. |
| VI. Documents modelled | ✅ This feature implements it, including the import-linter contract and the removal of every violation named in the principle. |
| Access model: network | ✅ Polling only. No new inbound endpoint. |
| Access model: 4th constraint | ✅ Nothing calls `transition` on an ingested issue. A test asserts it. |
| Persistence | ✅ Alembic-owned, stores own their sessions, naive UTC. |

Post-design re-check: no new violations. The Principle IV gap is accepted,
not resolved.

## Project Structure

### Documentation (this feature)

```text
specs/046-jira-first-alpha/
├── spec.md
├── plan.md            # this file
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── adf-mapping.md
│   ├── ports.md
│   └── liaison-turn.md
├── checklists/requirements.md
└── tasks.md           # /speckit-tasks
```

### Source code

```text
backend/
├── .importlinter                       # + documents-at-the-boundary contract
├── alembic/versions/0036_jira_channel.py
├── app/
│   ├── documents.py                    # constructs + builders only (pure)
│   ├── document_formats/               # NEW: the only parse/render code
│   │   ├── markdown.py                 # parse (commonmark+table) / render
│   │   ├── adf.py                      # parse / render (contracts/adf-mapping.md)
│   │   ├── text.py
│   │   └── json.py                     # persistence (was documents_json.py)
│   ├── ports.py                        # Person, Document-typed Task/Feedback
│   ├── persistence/
│   │   ├── document_column.py          # NEW: Document <-> JSON column type
│   │   ├── comment_store.py            # NEW: cursor + inbound comments
│   │   └── board_projection_store.py   # payload, task_ref, attempts
│   ├── services/
│   │   ├── jira.py, jira_document.py   # ADF in/out, reporter/change owner, /myself
│   │   ├── github*.py, gitlab.py, local_task_source.py   # Document-only
│   │   └── board/
│   │       ├── gates.py                # gate.opened event, reason rule, decided_by
│   │       ├── announcements/          # NEW: event → Document builders
│   │       ├── projection_retry.py     # NEW: retry loop
│   │       ├── comment_poll.py         # NEW: reply loop
│   │       ├── replies.py              # NEW: entitlement, routing, outcomes
│   │       ├── liaison.py              # NEW: interpretation turn
│   │       └── exec_summary.py, materialise.py, delivery_body.py  # build Documents
│   └── routers/board.py                # release continues held replies
├── specialists/liaison/                # NEW: manifest + prompt
└── tests/                              # mirrors the above

frontend/src/lib/personas.ts            # "decided by <name> via Jira"
docs/                                   # setup-jira-workflow.md, configuration.md
```

**Structure Decision**: the existing web-app layout. All new behaviour is
in the backend's service layer, under `services/board/`, so the layering
contract holds. The only new top-level package is `app/document_formats/`,
which is the mechanism Principle VI asks for.

## Phases (for `/speckit-tasks`)

1. **Setup:** Alembic 0036. Config fields (`change_owner_field`, the poll
   and retry intervals; `feedback_marker` revived).
2. **Foundational, Story 1 (P1):**
   - extend the constructs;
   - add `document_formats` and the ADF parser;
   - port types;
   - persistence and agent-boundary parsing;
   - remove every named violation;
   - add the import-linter contract.

   This blocks Stories 2 and 3.
3. **Story 2 (P1):**
   - `gate.opened` event;
   - announcement builders and service;
   - ledger payload and retry loop;
   - change-owner and reporter mentions;
   - status comments;
   - docs.
4. **Story 3 (P2):**
   - comment poller and stores;
   - entitlement;
   - screening and release continuation;
   - liaison specialist and turn;
   - reason rule in the backend;
   - attribution and feed;
   - reply confirmations;
   - end-to-end test.
5. **Polish:** quickstart run against Jira Cloud. Remove the dead
   `feedback_*` settings and `review_requests.py`. Close #65.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| New `liaison` specialist | A reply's meaning needs language understanding. A dedicated no-tools persona keeps it out of the coordinator's card flow. | Keyword matching ("approve") misreads plain language, and you asked for plain language with @kestrel. Reusing input-security mixes safety screening with intent. |
| Ticket users decide gates while kestrel stays single-user (Principle IV) | The alpha needs the reporter and change owner to act from Jira. | Amending Principle IV now: deliberately deferred to the access & identity epic (#81); the source's own access is the boundary meanwhile. |
| Document JSON in persistence (migration of two columns) | Principle VI makes persistence a boundary, and parsing Markdown wherever a Document is needed would put parsing in core code. | Storing Markdown and parsing on read everywhere (violates VI). |
