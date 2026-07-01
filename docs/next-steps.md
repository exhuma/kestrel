# Next steps

Status as of 2026-07-01: the feasibility spike, the live session-streaming
feature, the Mission Control redesign, and the first real workflow (GitHub
issue → refine → plan → implement → draft PR) are all merged and verified
end-to-end against a real repo (`exhuma/kestrel#1`, including a real merged
PR). This file tracks what's deliberately left undone, so the next session
can pick up without re-deriving it.

Items are grouped by where they came from, not by priority — pick whichever
serves what you need next. None of these have been brainstormed into a full
spec yet; each deserves its own design pass (`superpowers:brainstorming` →
`superpowers:writing-plans`) before implementation, per this repo's
convention.

## Small, contained fixes (deferred from the final workflow-feature review)

These were triaged as Minor / safe-to-defer at merge time — none are urgent,
all are quick:

- `backend/app/services/github.py:30` — `GitHubClient`'s `httpx.AsyncClient`
  is never explicitly closed. Bounded today (the client is a process-wide
  `lru_cache` singleton), but add `aclose()` behind a FastAPI lifespan hook
  if the service ever stops being a singleton.
- `backend/app/services/github.py:45` — `GitHubError` embeds the full,
  untruncated `resp.text` in its message. Truncate for very verbose error
  bodies (e.g. HTML from a proxy/rate-limit page).
- `backend/app/services/github.py:39` — `_request(**kw)` is untyped;
  tighten to the specific `httpx.AsyncClient.request` kwargs actually used
  (`json=`, `headers=`).
- `backend/app/routers/workflows.py:73,84,95` — `reply`/`approve`/`reject`
  return a bare `dict[str, str]` with no `response_model`, unlike `list`/`get`.
  Add a small `StatusOut` schema for OpenAPI completeness.
- `frontend/src/components/WorkflowPanel.vue:67-71` — `stepTone()` has a
  `'failed' → 'err'` branch that's dead code: only `WorkflowRun.status`
  reaches `"failed"`, never `WorkflowStep.status`. A failed run currently has
  no distinct visual state in the step tracker itself (only the top banner
  shows it). Either propagate a `failed` status onto the step that was
  running when the run died, or remove the dead branch.

## Explicitly out of scope for workflow v1

From `docs/superpowers/specs/2026-07-01-github-issue-workflow-design.md`:

- **Webhooks / auto-trigger** — start a workflow automatically from a
  GitHub issue event instead of manually via the UI.
- **Durable persistence** — `WorkflowRegistry` and `SessionRegistry` are
  in-memory only. A backend restart loses every session and workflow,
  including one sitting mid-approval. This is the most consequential gap:
  it blocks running this unattended or trusting it with anything long-lived.
- **Multi-user / auth** — single-user by design today; no login, no
  per-user isolation.
- **Retry or re-plan on reject** — rejecting a gate just ends the run.
  There's no "send it back with feedback and try again" loop; starting over
  means a brand new workflow run.
- **Incremental commits during implement** — the implement step makes one
  commit at the very end, not as the agent works.
- **Auto-merging the PR** — the workflow opens a draft PR only; merging is
  a manual human action on GitHub (by design — this is the review gate).

## Broader initiatives raised but not started

- **Persistence layer** (same gap as above, called out repeatedly as *the*
  natural next step): a real store (SQLite would be the lightest fit given
  the single-user scope) so sessions/workflows survive a restart. Doing
  this well means threading a repository/DAO layer under the existing
  `SessionRegistry`/`WorkflowRegistry` interfaces rather than changing their
  callers.
- **Session-level robustness & controls** — no "Stop" action exists to
  cancel a running session or workflow step from the UI; only process
  exit/crash ends it. Failure visibility for sessions has improved (workflow
  runs now surface `error` in the UI and log it server-side), but a
  user-initiated cancel is still missing everywhere.
- **DX / demo polish** — dev servers still require explicit env vars
  (`VITE_API_BASE`, `DISPATCHER_WORKSPACE_ROOT`, a free port) every time.
  Baking sane defaults (e.g. backend defaulting to port 8001, a committed
  `frontend/.env` pointing at it) would let `npm run dev` / `uv run
  uvicorn` just work.
- **Frontend bundle size** — the Vite build warns about a >500 kB chunk
  (`vite.config.ts` / build output). Not urgent for a single-user tool, but
  code-splitting (dynamic `import()` for the Workflows vs Sessions panels)
  would clean up the warning and improve first-load time.
