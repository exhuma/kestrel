# Quickstart & Validation: GitHub Ingestion & Repo Ops

Runnable scenarios that prove the feature end-to-end. See [spec.md](./spec.md) for
requirements, [contracts/](./contracts/) for interface shapes, and
[data-model.md](./data-model.md) for schema. Implementation lives in `tasks.md`
(next phase) and the code — not here.

## Prerequisites

- Backend deps: `cd backend && uv sync`. Frontend: `cd frontend && npm install`.
- Apply the new migration: `cd backend && uv run alembic upgrade head` (creates
  `webhook_delivery`, adds `workflow_run.source`).
- Config (`backend/.env`, never committed):
  ```
  KESTREL_GITHUB_TOKEN=<PAT with Contents, Issues, Pull requests>
  KESTREL_WEBHOOK_SECRET=<random high-entropy string>
  KESTREL_WATCHED_REPOS=owner/repo
  KESTREL_TRIGGER_LABEL=kestrel
  KESTREL_RECONCILE_INTERVAL_SECONDS=300
  KESTREL_PUBLIC_BASE_URL=https://<your-tunnel-host>   # optional; unset ⇒ link-less comments
  ```
- Expose the webhook endpoint to GitHub (operator's responsibility — tunnel/reverse
  proxy). Point a repo webhook at `POST {public}/api/github/webhook`, content-type
  JSON, secret = `KESTREL_WEBHOOK_SECRET`, events = *Issues*.

## Scenario 1 — Label an issue, a run starts (US1 / FR-001,002,004,005)

1. Start backend (`uv run uvicorn app.main:app`) and frontend (`npm run dev`).
2. On GitHub, add the `kestrel` label to an issue in the watched repo.
3. **Expect**: the run appears in the workflow list within seconds, identical to a
   manual run, with `source = github-issue`. GitHub's webhook deliveries page shows
   a `202`.
4. Re-deliver the same event (GitHub UI "Redeliver"). **Expect**: `200`, still
   exactly one run (dedup — FR-004).
5. Local signature check without GitHub: POST a crafted body with a **wrong**
   signature → `401`, no run. Correct HMAC (`sha256=` hex over the raw body with the
   secret) → `202`.

## Scenario 2 — Missed delivery caught by reconciliation (US2 / FR-012,013,014)

1. Disable/point the webhook away (simulate a missed delivery). Label a qualifying
   issue directly on GitHub.
2. Wait one `RECONCILE_INTERVAL_SECONDS` cycle. **Expect**: exactly one run starts.
3. Wait a second cycle. **Expect**: no second run (idempotent with the guard).
4. Temporarily set an invalid token to force a GitHub error. **Expect**: the cycle
   logs the failure, starts no run, and the next cycle recovers — the loop never
   dies (FR-014).

## Scenario 3 — Gate notification + deep-link (FR-023–031)

1. With `PUBLIC_BASE_URL` set, start a run and let it reach `awaiting_refine_input`.
2. **Expect**: a comment on the source issue — generic template text plus
   `Open in kestrel: {public}/?run=<id>` (FR-023/024). No plan/questionnaire content
   in the body (FR-031).
3. Click the link. **Expect**: the UI opens with that run selected and its
   questionnaire form shown (FR-028), after the shared-secret gate.
4. Advance through refine rounds and each approval gate. **Expect**: one new comment
   per gate entry, each with its own link (FR-025).
5. Unset `PUBLIC_BASE_URL` and re-run. **Expect**: comments still post, without the
   link line (FR-024).
6. Point the token/API base at an unreachable host to force a comment failure.
   **Expect**: the run still reaches and holds its gate, the failure is logged, and
   the gate is visible in the in-app notification center (FR-026/SC-010).

## Scenario 4 — Restart idempotency (FR-030 / R-07)

1. Drive a run to an `awaiting_*` gate (one comment posted).
2. Restart the backend. `recover()` re-parks the run at its gate.
3. **Expect**: **no** new comment on the issue, and no new in-app row — recovery
   re-enters the gate without `_save()`. (A backend unit test pins this: recovering
   an `awaiting_*` run does not invoke the notifier.)

## Scenario 5 — Concurrent same-repo isolation (US3 / FR-016,017,018)

1. Start two runs for the same watched repo within the same minute (e.g. label two
   issues).
2. **Expect**: each run has its own `git worktree` under `workspace_root`, its own
   branch, and neither sees the other's uncommitted changes; both share the per-repo
   bare mirror.
3. Abandon one (`DELETE /api/workflows/{id}`). **Expect**: its worktree is removed,
   the other run's worktree and git state are intact (FR-017).
4. Let a run finish. **Expect**: branch pushed, draft PR opened with the PR URL
   surfaced (unchanged external outcome — FR-018), and its worktree cleaned up (the
   done/failed leak is closed).

## Scenario 6 — Abandon does not resurrect (FR-008a / FR-013a)

1. Ingest a run for a labelled issue, then abandon it (`DELETE /api/workflows/{id}`)
   while the `kestrel` label is still on the issue.
2. Wait one reconciliation cycle. **Expect**: **no** new run — the issue is
   dismissed (no "zombie re-run"). A `labeled` redelivery also starts nothing.
3. Remove the `kestrel` label on GitHub, then re-add it. **Expect**: a fresh run
   starts (the dismissal was cleared when the label was removed).
4. Simulate a start failure (e.g. point at a non-existent issue): **Expect** outcome
   `run-failed`, no run row, and — because no dismissal is written — the next
   reconciliation cycle re-attempts the still-labelled issue (FR-013a).

## Automated test suites (Constitution III)

- **Backend (pytest)**: HMAC verify (valid/invalid/missing), delivery dedup + prune,
  label/repo/event gating, one-run-per-(repo,issue) guard, dismissal add/skip/clear
  (abandon → skip; label removed → clear), failed-start leaves no run/dismissal,
  reconciliation idempotency + failure-resilience, notifier composition +
  fire-and-forget failure, restart-idempotency guard, worktree isolation + cleanup,
  deep-link builder. httpx mocked; no real `claude`/GitHub/production DB.
- **Frontend (vitest)**: `/?run=<id>` on load calls `select` once and shows the
  workflows view; no param ⇒ normal empty state; `WorkflowDetail`/summary type
  includes `source`. All HTTP mocked.

Run: `cd backend && uv run pytest` and `cd frontend && npm run test`.

## Prerequisite task (Constitution I)

Record the webhook-exposure deviation in the constitution via
`/speckit-constitution` **before** relying on the off-loopback endpoint (see plan
Constitution Check). HMAC is the authenticity gate; exposure is the operator's
responsibility; the rest of the API stays loopback-bound.
