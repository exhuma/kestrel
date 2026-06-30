# Project Contract

Agent-dispatcher: a personal, single-user service that spawns coding-agent
sessions (Claude Code CLI) and monitors them from a web UI.

## Stack
- Backend: FastAPI (Python, uv) in `backend/`.
- Frontend: Vue 3 + Vuetify 4 + TypeScript (Vite, npm) in `frontend/`.

## Worker agent
- The backend invokes the host's logged-in `claude` CLI as a subprocess
  (Max subscription, OAuth). No `ANTHROPIC_API_KEY`; no Agent SDK.

## Spike scope and deliberate deviations
- Runs directly on the host (uv / vite dev), NOT in Docker or a
  devcontainer — the backend must reach the host `claude` binary and its
  `~/.claude` OAuth credentials. Dockerisation is deferred.
- State is in-memory only. No database, no auth, single concurrent user.
- One hard-coded happy path (start a session, resume it).

## Type contract
- Frontend business types in `frontend/src/types/` mirror the backend
  JSON shapes (`SessionSummary`, `SessionEvent`). Keep them in sync when
  the API changes.
