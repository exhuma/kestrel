# M-H · Deferred / Optional — Backlog

> **STATUS: BACKLOG.** Not a sequenced plan. Each item below is
> picked up on demand and gets its own spec→plan cycle
> (superpowers:brainstorming → superpowers:writing-plans) when its
> time comes. Listed here so the roadmap is complete and nothing is
> silently forgotten.

None of these block the kestrel MVP (M-A..M-G).

## H-1 · Access gate (low priority, by design)

Single-user protection against tampering — explicitly *not*
multi-user auth.

- Backend: middleware checking a single shared bearer secret
  (`KESTREL_ACCESS_TOKEN`) on `/api/*`, exempting
  `/api/webhooks/github` (which has its own HMAC).
- Frontend: the existing `TokenProvider` seam in
  `frontend/src/api/index.ts` already injects
  `Authorization: Bearer …` — add a minimal token-entry screen
  persisting to localStorage.
- Out of scope: users, roles, sessions, OIDC.

## H-2 · Additional Notifier back-ends

Drop-in implementations of the M-F `Notifier` protocol; zero
orchestrator changes by design.

- **ntfy/webhook push** — simplest self-hosted push channel.
- **Email** — e.g. SMTP, or via the claude.ai Gmail connector
  (requires the user to authorize the connector in claude.ai
  settings first; unavailable until then).
- Config: extend `KESTREL_NOTIFIERS` list; each back-end brings its
  own settings fields.

## H-3 · Planka source

`TaskSource` implementation for a Planka kanban board.

- Trigger: polling (Planka webhook support is limited) — reuses the
  M-C reconcile loop pattern.
- Mapping: card → work item; card description → issue body
  equivalent; kestrel comments → card comments; "PR" equivalent:
  link the GitHub PR on the card and move it to a "review" list.
- Open question for its brainstorm: which board/list denotes
  "kestrel, please work on this"?

## H-4 · Zammad source

`TaskSource` implementation for Zammad tickets.

- Trigger: Zammad webhooks (it has real webhook support) → same
  ingress pattern as GitHub (secret-verified, dedup).
- Mapping: ticket → work item; kestrel replies as ticket articles
  (internal notes for interview, public for status); PR link posted
  as the closing note.
- Open question for its brainstorm: which ticket state/tag opts a
  ticket in?

## H-5 · Quality-of-life candidates (unranked)

Captured from spike learnings; promote to a real item when felt.

- True token-by-token streaming (the spike's known limitation:
  events currently arrive when the run completes; needs the
  `on_id` early-return upgrade in the runner).
- Concurrency limits (max parallel claude sessions) and a queue.
- Retention/cleanup: prune old events, workspaces, worktrees.
- Quota awareness: surface `rate_limit_event` data in the UI so
  the user sees Max-quota pressure before hitting it.
