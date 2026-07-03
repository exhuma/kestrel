# Next steps

Status as of 2026-07-03: **first alpha shipped.** The MVP workflow (GitHub
issue → refine → clarify → plan → implement → draft PR, with human approval
gates and pause/resume at every stage) is complete, persisted, and verified
end-to-end against real GitHub issues and PRs. Kestrel is packaged as a
CalVer-tagged Docker image (`Dockerfile`, `docker-compose.yml`,
`.github/workflows/release.yml`). Roadmap milestones M-A, M-B, M-D, M-E, M-F,
M-G are all done — see `docs/superpowers/plans/kestrel-roadmap.md` for the
full history and each milestone's plan doc.

This file tracks what's deliberately left undone, so the next session can
pick up without re-deriving it. None of these have been brainstormed into a
full spec yet (except M-C, which has a draft plan); each deserves its own
design pass (`superpowers:brainstorming` → `superpowers:writing-plans`)
before implementation, per this repo's convention.

## Next milestones (roadmap)

- **M-C · GitHub ingestion & repo ops** —
  `docs/superpowers/plans/2026-07-01-kestrel-m-c-github.md` (DRAFT,
  task-level; its own reconciliation note says `GitHubClient`/`GitService`/
  draft-PR creation already exist, so remaining scope is narrower than the
  original draft: webhook ingress with HMAC + dedup, poll reconciliation as
  a safety net, and per-run `git worktree` isolation instead of one shared
  clone). This is what turns kestrel from "start a run by clicking a button"
  into "kestrel notices a new/updated issue on its own."
- **M-H · Deferred / optional backlog** —
  `docs/superpowers/plans/2026-07-01-kestrel-m-h-deferred.md`. Unordered,
  pick on demand:
  - **H-1 Access gate** — single shared-secret bearer auth on `/api/*`
    (frontend `TokenProvider` seam already exists).
  - **H-2 More Notifier back-ends** — ntfy/webhook push, email (SMTP or the
    claude.ai Gmail connector once authorized). Zero orchestrator changes
    needed; drop-in against the existing `Notifier` protocol.
  - **H-3 Planka source**, **H-4 Zammad source** — additional `TaskSource`
    implementations.

## Gaps found operating the alpha (not yet triaged into a plan)

- **No retry/resume path for a `failed` run.** The state machine only has
  `WorkflowService.create()` (fresh start); there's no transition that
  re-enters a run stuck in `status: "failed"` (e.g. after a transient
  subprocess crash) without abandoning it and starting a brand-new run on
  the same issue. Hit for real on `exhuma/kestrel#8` (a `LimitOverrunError`
  crash, since fixed — see `backend/app/services/runner.py`'s
  `_STREAM_LIMIT`) — the old run (`wf-1086a757`) is permanently stuck in
  `failed` with no in-place way to resume it.
- **No `/health` endpoint.** Now that kestrel ships as a Docker image, a
  liveness/readiness route would let `docker-compose`/orchestrators actually
  monitor it. Currently returns a bare 404.

## Small, contained fixes (deferred from earlier reviews, still open)

Re-checked 2026-07-03 against current code — none of these were touched by
M-B through M-G, all are still quick and still safe to defer:

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
- `backend/app/routers/workflows.py:76,87,98` — `reply`/`approve`/`reject`
  return a bare `dict[str, str]` with no `response_model`, unlike `list`/
  `get`. Add a small `StatusOut` schema for OpenAPI completeness.
- `frontend/src/components/WorkflowPanel.vue:104` — `stepTone()` has a
  `'failed' → 'err'` branch that's still dead code: only `WorkflowRun.status`
  reaches `"failed"`, never `WorkflowStep.status`. A failed run still has no
  distinct visual state in the step tracker itself (only the top banner
  shows it). Either propagate a `failed` status onto the step that was
  running when the run died, or remove the dead branch.

## DX / demo polish (still open)

- Dev servers still require explicit env vars (`VITE_API_BASE`,
  `KESTREL_WORKSPACE_ROOT`, a free port) every time. Baking sane defaults
  (e.g. backend defaulting to port 8001, a committed `frontend/.env`
  pointing at it) would let `npm run dev` / `uv run uvicorn` just work.
  `frontend/src/api/index.ts` still defaults `API_BASE` to
  `http://localhost:8000`, which doesn't match the port actually used in
  local dev (8001) unless `VITE_API_BASE` is set.
- Frontend bundle size — last checked, the Vite build warned about a
  >500 kB chunk. Not urgent for a single-user tool, but code-splitting
  (dynamic `import()` for the Workflows vs Sessions panels) would clean up
  the warning and improve first-load time. Not re-verified this session.

## Explicitly out of scope (by design, not gaps)

- **Multi-user / auth** — single-user by design; H-1's access gate is the
  only planned protection, and it's explicitly *not* multi-user auth.
- **Auto-merging the PR** — the workflow opens a draft PR only; merging is
  a manual human action on GitHub (the review gate, by design).
- **Incremental commits during implement** — the implement step makes one
  commit at the end, not as the agent works.
