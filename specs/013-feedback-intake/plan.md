# Implementation Plan: Feedback Intake

**Branch**: `013-feedback-intake` | **Date**: 2026-09-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/013-feedback-intake/spec.md`

## Summary

Give kestrel a way to receive human input from where humans already are —
ticket comments and PR/MR review feedback — instead of only through its own
web UI. An explicit trigger marker (default `@kestrel`) gates every piece of
feedback; a single intake service (fed by the GitHub webhook for GitHub and by
extending the existing poll loops for Jira/GitLab/fixture) converges webhook
and poll delivery onto one dedup'd, durable queue. Feedback maps onto the
pipeline differently depending on run state: a parked gate treats it as
reject-with-feedback (reusing `describe()`/`refine()`'s existing loops
unchanged); an autonomous phase queues it for the next round/step boundary; a
finished run is revived (if its branch/PR is still open) or spawns a
clearly-linked successor; review feedback resumes the *same* branch and a
cheap triage turn decides which pipeline step to resume at.

## Technical Context

**Language/Version**: Python 3.12 (backend, `uv`) — unchanged. No new
frontend surface is required by any functional requirement in `spec.md`; the
feature is backend-only for this plan (TypeScript/Vue 3 stack stays
untouched unless a follow-up decides feedback state needs its own UI).

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x, Alembic, `httpx`
(existing — GitHub/Jira/GitLab clients already use it for every request).
No new runtime dependency.

**Storage**: SQLite via SQLAlchemy 2.x, schema owned by Alembic. **New
migration required** (`0015_feedback.py`): two new tables
(`feedback_item`, `feedback_cursor`) and one new nullable column
(`workflow_run.pr_number`). Unlike feature 012, a migration is warranted and
accepted here — durable dedup and a durable mid-run queue are load-bearing
for FR-004 (never act twice) and FR-007 (never lose queued feedback across a
restart); neither can be satisfied by in-memory state alone.

**Testing**: pytest with every `TaskSource`/`CodeHost`/agent-backend call
mocked or stubbed (Constitution III) — no real GitHub/Jira/GitLab API, no
real `claude` subprocess. New coverage mirrors the existing per-source
contract-test shape (`test_github_ports.py`, `test_jira_client.py`,
`test_fixture_task_source.py`) plus new dispatch/triage/resume unit tests.

**Target Platform**: single-user Linux service, unchanged. The GitHub
webhook's off-loopback exposure is **already** a recorded constitutional
deviation (v1.4.0, "Access model") scoped to the endpoint itself
(`POST /api/github/webhook`) and its HMAC gate — adding `issue_comment`,
`pull_request_review`, and `pull_request_review_comment` as new handled
event *types* on that same endpoint, under the same HMAC verification,
requires no new deviation and no constitution amendment.

**Project Type**: web application (FastAPI backend in `backend/`) —
unchanged; this feature does not touch `frontend/`.

**Performance Goals**: not latency-sensitive. GitHub feedback arrives near
webhook-delivery speed; Jira/GitLab/fixture feedback arrives within one
`poll_interval_seconds` cycle (existing default 300s), matching every other
poll-sourced signal in the system today.

**Constraints**: every piece of feedback MUST carry the configured trigger
marker or be ignored outright (FR-003); the same feedback MUST never be
acted on twice, including across a restart (FR-004); kestrel MUST never
react to its own output (FR-005); comment volume MUST NOT grow with the
number of feedback rounds (FR-015) — reuses the `TaskSourceNotifier.
_last_notified` dedup pattern already shipped for the same reason (comment
fatigue was a real, previously-reported problem).

**Scale/Scope**: unchanged order of magnitude — single maintainer, a
handful of concurrent runs, human-authored (low-volume) feedback.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.4.0.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Contract Fidelity | ✅ | No new off-loopback endpoint — new event types ride the *already-recorded* webhook exception, same HMAC gate. No frontend type contract touched (no new business type crosses to `frontend/src/types/`) since this plan adds no UI surface. |
| II. Layered, Backend-Owned Architecture | ✅ | All new logic (`services/feedback/`, port extensions, driver resume path) lives in backend services behind routers; schema change goes through Alembic (`0015_feedback.py`), no `create_all`/raw DDL. |
| III. Test-First Discipline | ✅ | Every new port method (`list_comments`, `acknowledge`, `get_change_request`, `list_review_comments`) gets a mocked contract test per source; driver-level tests use the existing `conftest.py` fakes; no real subprocess/API/DB. |
| IV. Deliberate Simplicity & Single-User Scope | ⚠️ **Justified complexity** | This is a materially larger feature than 011/012 — see Complexity Tracking below. Each addition is traced to a specific FR; nothing here is speculative (e.g. gitea review-reads are explicitly deferred, not spec'd, since no FR requires them yet). |
| V. Kit-Aligned Consistency & Observability | ✅ | `resolve_kits` attempted per task (Quartermaster unavailable this session — proceeding is consistent with prior practice this session of not blocking on a down MCP server). No new UI, so no theme-token question. Feedback-pipeline outcomes (marker-matched / claimed / dispatched / applied / ignored) logged the same structured way `ingestion.py` already logs `ingest outcome=...`. |

**Gate result**: PASS with one justified-complexity note (Principle IV),
recorded in Complexity Tracking — consistent with how feature 012 recorded
its own justified additions rather than treating the gate as a hard block.

**Post-Phase-1 re-check**: `data-model.md` and the three `contracts/*.md`
files introduce nothing beyond what this table already accounts for — the
migration, the new `services/feedback/` package, `add_worktree_existing`,
and the triage turn are exactly the four items in Complexity Tracking, with
no fifth surprise. Gate remains PASS.

## Project Structure

### Documentation (this feature)

```text
specs/013-feedback-intake/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/
│   ├── feedback-source-port.md
│   ├── feedback-dispatch.md
│   └── change-request-resume.md
├── checklists/
│   └── requirements.md
└── tasks.md              # /speckit-tasks output (not created here)
```

### Source code (repository root) — files touched / added

```text
backend/app/
├── ports.py                            # EXTEND — Feedback/ChangeRequest dataclasses;
│                                        #          TaskSource.list_comments/acknowledge;
│                                        #          CodeHost.get_change_request/
│                                        #          list_review_comments/acknowledge/
│                                        #          change_request_number
├── config.py                           # EXTEND — feedback_marker, feedback_ignore_authors,
│                                        #          feedback_window_days settings
├── services/
│   ├── github.py                       # EXTEND — list_issue_comments, get_pull_request,
│   │                                    #          list_pull_reviews,
│   │                                    #          list_pull_review_comments, acknowledge
│   ├── jira.py                         # EXTEND — list_comments; acknowledge -> False
│   ├── fixture.py                      # EXTEND — reads <slug>.comments.jsonl;
│   │                                    #          acknowledge -> False
│   ├── gitlab.py                       # EXTEND — get_change_request, list_review_comments,
│   │                                    #          acknowledge via award_emoji
│   ├── git.py                          # EXTEND — add_worktree_existing (resume a branch)
│   ├── poll_source.py                  # EXTEND — register FeedbackPollService
│   ├── ingestion.py                    # UNCHANGED — maybe_start_run reused as-is for
│   │                                    #             linked-successor creation
│   └── workflows/
│       ├── driver/
│       │   ├── __init__.py             # EXTEND — deliver() idempotent when pr_number
│       │   │                           #          already open (push-only, one comment)
│       │   ├── resume.py               # NEW — mirror ensure -> add_worktree_existing ->
│       │   │                           #        _ensure_artifact_dir -> continue_run
│       │   └── escalate.py             # UNCHANGED — resume path retries from base branch
│       │                               #             when no existing branch to resume
│       ├── reentry.py                  # NEW — rewind_to(run, step, instruction): pure
│       │                               #        step-state rewind, generalises
│       │                               #        _seed_from_sentinel's pre-mark trick
│       └── prompts_feedback.py         # NEW — FEEDBACK_TRIAGE_PROMPT (prompts.py is at
│                                        #        417/500 lines; new prompt lives here)
├── services/feedback/                  # NEW package
│   ├── marker.py                       # Trigger-marker + author-denylist matching
│   ├── intake.py                       # FeedbackIntakeService — single convergence point
│   ├── github_events.py                # Per-event demux for the webhook (keeps the
│   │                                   #  router thin)
│   ├── poll.py                         # FeedbackPollService (PollSource protocol)
│   ├── dispatch.py                     # FeedbackDispatcher — routes by run.status
│   └── triage.py                       # Triage turn: classify feedback -> target step
├── persistence/
│   ├── tables.py                       # EXTEND — FeedbackItemRow, FeedbackCursorRow,
│   │                                   #          WorkflowRunRow.pr_number
│   └── feedback_store.py               # NEW — FeedbackStore (claim/queued_for/mark/
│                                       #        cursor/set_cursor)
├── services/workflow_text.py           # EXTEND — extract_feedback_triage()
└── routers/
    └── github_webhook.py               # EXTEND — issue_comment, pull_request_review,
                                        #          pull_request_review_comment events

backend/alembic/versions/0015_feedback.py   # NEW migration

backend/tests/…                        # NEW tests per Constitution III (see below)
docs/architecture.md, docs/*           # UPDATE — feedback-intake narrative, operator
                                        #          guidance for the trigger marker
```

**Structure Decision**: Additive-in-place, matching feature 012's precedent:
extends existing per-source adapters (`github.py`/`jira.py`/`fixture.py`/
`gitlab.py`) and the existing driver/prompts modules rather than
introducing a parallel pipeline. The one new top-level package,
`services/feedback/`, is warranted (not additive-in-place) because intake/
dispatch/triage is a genuinely new cross-cutting concern with no existing
home — forcing it into `services/workflows/` would make an already-large
package (the driver alone is at 460/500 lines) responsible for a concern
distinct from step execution.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|----------------------------------------|
| **New Alembic migration** (2 tables + 1 column) | FR-004 (never act twice, incl. across restart) and FR-007 (queued feedback survives a restart) need durable, atomic dedup — the in-memory `_Control.replies` queue that exists today is explicitly *not* durable | Deriving dedup from existing timestamps (e.g. "comments newer than the run's last activity") was considered and rejected: restart/clock-skew edge cases could silently re-process or miss a comment, which directly violates FR-004/FR-005's "never twice" and "never self-trigger" guarantees — the cost of a migration is smaller than the cost of an intermittent double-action bug |
| **New `services/feedback/` package** (5 new modules) | Intake (webhook + poll convergence), dispatch (routing by run state), and triage (LLM step-classification) are a distinct cross-cutting concern from step execution, with no existing home | Folding it into `services/workflows/driver/` was considered and rejected: that package is already at 460/500 lines (feature 012 already flagged this ceiling), and intake/dispatch conceptually parallel `IngestionService`'s existing role (run *creation*) rather than the driver's role (run *execution*) |
| **New `add_worktree_existing` + `driver/resume.py`** | FR-008 (amend the *same* PR) is impossible without a way to check out an existing branch — `drive()` today always cuts a fresh branch off base | A "new run, new PR" fallback for all review feedback was considered (explicitly offered as an option during requirement-gathering) and rejected by the maintainer: it fragments the review thread and leaves the original PR stale, which is the exact problem this feature exists to solve |
| **New triage turn** (`services/feedback/triage.py`) | FR-009/FR-010 require picking the *right* pipeline step to resume at (an implementation nit vs. a design-invalidating comment are different re-entry points), and the maintainer explicitly chose "any step, LLM-classified" over a fixed re-entry point | A fixed re-entry point (always `code`, per the cheaper alternative offered during requirement-gathering) was rejected: it cannot satisfy FR-010 (re-opening a requirements-level decision when warranted), so feedback calling the underlying approach into question would be silently mis-applied as an implementation tweak |

**Not added** (YAGNI):
- **No gitea review-read support.** `services/gitlab.py`'s adapter is reused
  for gitea today (routing, not a real gitea client), and gitea's notes/
  reaction endpoints differ from GitLab's. No FR requires gitea feedback
  specifically; shipping GitLab-only and returning `[]` for gitea (degraded,
  not wrong) avoids building against undocumented/unverified endpoints.
- **No new frontend surface.** No FR in `spec.md` requires kestrel's UI to
  visualize queued/applied feedback — the observable effect (a revised
  deliverable, new commits, a new run) is already visible through existing
  UI. Adding one would be speculative ahead of real usage.
- **No configurable per-source marker.** One global `feedback_marker`
  setting, not one per task source — the spec's Assumptions section frames
  this as an organization-wide convention, not a per-integration one; a
  per-source override was not requested and would be speculative generality
  ahead of a demonstrated need.
