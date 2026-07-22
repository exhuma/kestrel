# Implementation Plan: GitHub Ingestion & Repo Ops

**Branch**: `002-github-ingestion` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-github-ingestion/spec.md`

## Summary

Turn kestrel from "click a button to start a run" into "notices flagged issues on
its own", and make concurrent same-repo runs safe:

1. **Webhook ingress** (P1) — a single new HTTP endpoint accepts GitHub `issues`
   webhooks, verifies each delivery's `X-Hub-Signature-256` HMAC in constant time,
   dedupes on `X-GitHub-Delivery`, and starts a run for a watched repo's issue
   that gains the trigger label. Reuses the existing `WorkflowService.create()`
   path so ingested runs are indistinguishable from manual ones (the `source`
   discriminator is persisted-only — never surfaced to the API/UI). Abandoning a
   run records a durable **dismissal** so a still-labelled issue is not re-ingested
   (cleared when the trigger label is removed).
2. **Poll reconciliation** (P2) — a background loop launched in the app lifespan
   lists each watched repo's trigger-labelled issues and starts any run the
   webhook path missed; idempotent with webhooks via a one-run-per-(repo,issue)
   guard.
3. **Per-run worktree isolation** (P3) — replace the per-run full `git clone` with
   a per-repo shared bare mirror plus a per-run `git worktree`, serialised by a
   per-repo async lock, and clean the worktree up on *every* terminal outcome (not
   only abandon, which is the sole cleanup path today).
4. **Gate notifications & deep-links** (P1) — compose a `GitHubIssueNotifier`
   alongside the existing `InAppNotifier` at the `_save()` choke point so every
   `awaiting_*` gate posts a deterministic comment on the source issue, carrying a
   deep-link (`<public_base_url>/?run=<id>`) that opens the run's active gate form.
   Best-effort and fire-and-forget; the in-app notification is the fallback.

The one binding-constraint tension — the webhook endpoint must be reachable by
GitHub, contradicting the constitution's loopback-bound API — is reconciled by
making the HMAC signature the authenticity gate for that single endpoint and
recording the deviation in the constitution (see Constitution Check).

## Technical Context

**Language/Version**: Python 3.12 (`backend/.python-version`, `uv`); TypeScript 5
(frontend, Vite + npm).

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x + Alembic, httpx (async GitHub
client, already present), Pydantic Settings; Vue 3 + Vuetify 4 (Composition API).
No new runtime dependency is required — HMAC uses the stdlib `hmac`/`hashlib`;
worktrees use the existing `git` subprocess helper.

**Storage**: SQLite via SQLAlchemy, schema owned exclusively by Alembic
(`backend/alembic/versions/`). New migration `0006` adds the delivery-dedup table,
the issue-dismissal table, and a `source` column on `workflow_run`.

**Testing**: pytest (backend), vitest (frontend). Frontend tests mock all HTTP;
backend tests must not hit a real `claude` subprocess or GitHub.

**Target Platform**: Linux server / container (bundled Docker image) and a
run-from-source dev flow (uv / vite) — both MUST keep working.

**Project Type**: Web application (FastAPI backend + Vue/Vuetify SPA).

**Performance Goals**: Webhook handler MUST acknowledge fast enough that GitHub
does not mark the delivery failed (target < 2 s; run creation is dispatched to a
background task and never blocks the ACK — FR-005). Reconciliation interval is
configurable (default 300 s).

**Constraints**: Single concurrent user; secrets never logged (FR-006/SC-007);
processed-delivery store stays bounded (FR-008/SC-008); the rest of the API stays
loopback-bound — only the webhook endpoint is exposed.

**Scale/Scope**: One maintainer, a maintainer-configured allow-list of watched
repos (single digits), low webhook volume. No horizontal scaling.

## Constitution Check

*GATE: evaluated against `.specify/memory/constitution.md` v1.2.0.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Contract Fidelity | ✅ **Deviation recorded** | The webhook endpoint is reachable by GitHub — a deliberate departure from the "loopback-bound" access model. As Principle I requires, this is now **recorded in the constitution** (amendment 1.1.0 → 1.2.0: *Access model* bullet, with HMAC as the authenticity gate) before it is relied upon. The type contract is unaffected: `source` is persisted-only and NOT added to the API schema or `frontend/src/types/` (clarification Q3), and the deep-link adds no new frontend type — so no cross-language shape changes. |
| II. Layered, Backend-Owned Architecture | ✅ | All ingestion/verification/reconciliation logic lives in backend services/routers. Signature verification and label/repo gating are backend-enforced; the frontend deep-link only *selects* a run (UX). Schema changes go through Alembic `0006` — no `create_all`/raw DDL. |
| III. Test-First Discipline | ✅ | Each unit ships with tests: HMAC verify (valid/invalid/missing), delivery dedup, label/repo gating, one-run-per-issue, reconciliation idempotency, worktree isolation + cleanup, notifier composition + fire-and-forget failure path, deep-link URL builder, frontend deep-link select. No real `claude`/GitHub in tests (httpx mocked). |
| IV. Deliberate Simplicity & Single-User Scope | ⚠️ **Justified complexity** | Three additions carry justified complexity — the per-repo worktree lock + shared bare mirror, the reconciliation background loop, and the delivery-dedup store. Each is recorded in Complexity Tracking with the simpler alternative and why it is insufficient. No multi-user auth is introduced; HMAC is a shared-secret gate, consistent with the "shared-secret gate only" rule. |
| V. Kit-Aligned Consistency & Observability | ✅ | Structured logging records every delivery outcome (accepted / rejected-signature / duplicate / ignored / run-started / run-failed — FR-021) with secrets redacted. No hard-coded colours (deep-link is a plain URL). `.env.example` documents new settings; `.env` stays untracked. Kits resolved per task. |

**Gate result**: PASS. The prerequisite constitution amendment recording the
webhook-exposure deviation is done (v1.2.0), so no gate remains open.

## Project Structure

### Documentation (this feature)

```text
specs/002-github-ingestion/
├── plan.md              # This file
├── research.md          # Phase 0 output — decisions & rationale
├── data-model.md        # Phase 1 — entities, tables, migration
├── quickstart.md        # Phase 1 — runnable validation scenarios
├── contracts/           # Phase 1 — webhook, notifier, deep-link, client methods
│   ├── webhook-ingress.md
│   ├── github-client.md
│   ├── gate-notification.md
│   └── deep-link.md
├── checklists/
│   └── requirements.md  # (existing) spec quality checklist
└── tasks.md             # Phase 2 — created by /speckit-tasks, NOT here
```

### Source code (repository root) — files touched / added

```text
backend/app/
├── config.py                      # + public_base_url, webhook_secret,
│                                   #   watched_repos, trigger_label,
│                                   #   reconcile_interval_seconds (+ validators)
├── main.py                        # register webhook router; launch + cancel the
│                                   #   reconciliation task in _lifespan
├── models_workflow.py             # WorkflowRun.source ("manual" | "github-issue")
├── notifications.py               # GitHubIssueNotifier + CompositeNotifier;
│                                   #   deep-link appended to reused templates
├── routers/
│   └── github_webhook.py          # NEW — POST /api/github/webhook (+ HMAC dep)
├── services/
│   ├── github.py                  # + create_issue_comment, list_issues_by_label
│   ├── git.py                     # + bare-mirror clone, worktree add/remove,
│   │                               #   per-repo async lock
│   ├── ingestion.py               # NEW — verify→dedup→dismissal→gate→start,
│   │                               #   shared by webhook + reconciliation
│   └── reconcile.py               # NEW — periodic loop: start missing runs AND
│                                   #   clear dismissals for no-longer-labelled issues
├── persistence/
│   ├── tables.py                  # + WebhookDeliveryRow, IssueDismissalRow;
│   │                               #   workflow_run.source
│   ├── webhook_delivery_store.py  # NEW — dedup store (seen? + prune)
│   └── dismissal_store.py         # NEW — add/clear/is_dismissed per (repo,issue)
└── services/workflows.py          # create(source=...); one-run-per-(repo,issue)
                                    #   guard; record dismissal on abandon (delete);
                                    #   worktree provisioning + cleanup on
                                    #   done/failed; compose notifier in factory

backend/alembic/versions/
└── 0006_ingestion.py              # NEW — webhook_delivery + issue_dismissal tables
                                    #   + workflow_run.source column

frontend/src/
├── main.ts                        # read ?run=<id> at load → useWorkflows().select
└── composables/useWorkflows.ts    # optional: reflect selection back to URL
                                    #   (no type change — `source` stays backend-only)

docs/
├── configuration.md               # new settings
└── setup-github-workflow.md       # webhook setup + exposure guidance
```

**Structure Decision**: Existing web-app layout (Option 2) is retained; no new
top-level projects. Ingestion is factored into two small services
(`ingestion.py`, `reconcile.py`) so the webhook router and the reconciliation loop
share one "verify→dedup→gate→start" path (DRY, and it is the natural home for the
FR-019 task-source concern), keeping `workflows.py` focused on run execution.

**Extensibility / future sources (seam, not framework)**: More sources (Jira soon,
then GitLab/Planka) are planned but explicitly **out of scope** here (see spec
Assumptions → *Multi-source is a future direction*). Decision: *seam now, extract
with the second source*. This feature ships GitHub only; the abstraction is
extracted during the Jira feature when two concrete implementations exist, avoiding
an interface guessed from one. The boundaries are already port-shaped: the
`Notifier` protocol is the **outbound** port (a future `JiraNotifier` is just
another implementation), and `ingestion.py` + the `source` discriminator are the
**inbound** seam (a future `JiraIngress` slots in there). The load-bearing axis is
**Task Source vs Code Host** — GitHub collapses both (so `WorkflowRun.repo` +
`issue_number` and same-client PRs are acceptable *here*), but Jira is a task source
whose code lives in a separate repo (needs ticket→repo resolution). Implementation
MUST NOT add GitHub coupling beyond what GitHub needs, so that split can be
introduced later without reworking run execution.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| **Constitution amendment** to record the webhook-exposure deviation from the loopback-bound access model *(done — v1.2.0)* | Principle I forbids relying on an undocumented departure from the recorded access model; the webhook MUST be reachable by GitHub | Not amending = silently contradicting the constitution, which Principle I/Governance classifies as a defect. HMAC is the authenticity gate; exposure is the operator's responsibility; the rest of the API stays loopback |
| **Per-repo async lock + shared bare mirror** for worktrees | Ingestion makes concurrent same-repo runs normal; `git worktree add`/`remove` and the shared object DB are not safe to run unserialised, and the milestone explicitly calls for worktree isolation | Keeping per-run full clones (today's behaviour) re-downloads the entire repo for every issue — multiplied by ingestion — and still leaves the current on-done/on-failed workspace **leak** unfixed. A single global lock (not per-repo) would needlessly serialise unrelated repos |
| **Reconciliation background loop** | Webhooks are best-effort; a missed delivery must still produce a run (FR-012/SC-002). No existing scheduler | A manual "re-scan" button reintroduces the very "notice and re-trigger by hand" the milestone removes. Cron/external scheduler adds an operational dependency for a single-user tool |
| **Webhook-delivery dedup store** (new table) | At-most-once action per delivery across GitHub retries (FR-004); must survive restart (FR-022) and stay bounded (FR-008/SC-008) | In-memory dedup loses state on restart and double-starts on retry-after-restart. Bound is kept by pruning rows past GitHub's retry window on insert |
| **Issue-dismissal store** (new table) | Abandon must suppress re-ingestion of a still-labelled issue (FR-008a); must survive restart and be cleared when the label is removed | Without it, reconciliation re-creates an intentionally abandoned run every cycle ("zombie re-run"). A pure in-memory flag loses the dismissal on restart, resurrecting the run. Cleared on `unlabeled` webhook or when reconciliation sees the label gone |

**Not added** (YAGNI): no retry queue / catch-up sweep for failed gate comments
(clarified: in-app notification is the fallback); no dedicated retry queue for
failed run-starts (clarified Q2 / FR-013a: reconciliation is the retry path — a
failed start leaves no run record, so the next cycle re-attempts the still-labelled
issue); no per-run "last gate notified" marker (restart idempotency is inherited —
recovered gates re-park **without** re-calling `_save()`, so the notifier never
re-fires; see research R-07); no GitHub App / installation tokens (auth model
unchanged).
