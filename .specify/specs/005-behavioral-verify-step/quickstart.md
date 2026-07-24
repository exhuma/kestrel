# Quickstart: validating behavioral verify evidence

## Prerequisites

- A working kestrel dev setup (`docs/getting-started.md` or the run-from-source
  flow), with a `claude` login on the host that has access to whatever tool
  you want verify's explore turn to use (e.g. a Playwright MCP server
  configured in `~/.claude.json` on the host, for a UI-boundary check).
- A target repository with either a runnable HTTP API (e.g. a small FastAPI
  app) or a runnable web UI (e.g. a Vite dev server) reachable from inside
  the run's worktree.
- `config.toml` pointing `[[task_sources]]`/`[step_backends]` at that
  repository as usual (see `config.toml.example`).

## Scenario A — HTTP boundary

1. Start a workflow run against a repo whose PRD describes an HTTP endpoint
   behavior change (e.g. "the API should reject empty titles with a 422").
2. After `design` completes, confirm `WorkflowRun.boundary == "http"` (check
   via the workflow detail — or, until/unless this is exposed in an API
   field, via a debug log / DB inspection of the new column) before `code`
   starts.
3. Let the run proceed through `code` → `verify`. Watch the verify step's
   session transcript: the explore turn should show it launching the app
   (e.g. `uvicorn ...`) and issuing a real request.
4. On completion (`done` or `escalated`), open
   `.kestrel/<date>-<serial>/verify-report.md` in the run's branch/PR and
   confirm it lists at least one `kind="http"` observation with a concrete
   request/response description — this is the check for spec **SC-001**.

## Scenario B — UI boundary

Same as Scenario A, but with a PRD describing a UI behavior change (e.g. "the
login button should show a spinner while authenticating") and a repo with a
`npm run dev`/`preview` script. Confirm `boundary == "ui"` after design, and
that the verify report's observation describes a real browser interaction
(not just "the code looks like it adds a spinner").

## Scenario C — degraded verification (no boundary tooling)

Run Scenario B against a `claude` login that has **no** browser-automation
MCP server configured. Confirm the verify round's feedback explicitly states
that UI verification was degraded/incomplete due to missing tooling — this
is spec **SC-003** — rather than reading like an ordinary pass.

## Scenario D — hard gate vs. advisory feedback

Craft (or mock, in a backend test) a verify round where all checks and
behavioral observations pass, but the verifier also notes a code-quality
concern (e.g. a missing docstring). Confirm the round is still **accepted**
and the concern appears only in `feedback` — this is spec **SC-005** and
`test_verify_loop.py`'s new coverage for User Story 2.

## Scenario E — no cross-run contract

Complete one run against a repo (producing a `verify-report.md`). Start a
second, unrelated run against the same repo whose change intentionally
contradicts something the first run's report described. Confirm the second
run's verify step is judged only on its own PRD/design/live behavior — this
is spec **SC-006**; no test or manual check should need to delete the first
run's artifact for the second run to pass.

## Automated coverage

The equivalent of Scenarios A–E should exist as backend tests extending
`backend/tests/test_verify_loop.py` (mocked backend/session, no real `claude`
subprocess or real app process — per Constitution Principle III) plus new
coverage for `extract_boundary` (`backend/tests/test_workflow_text.py` or
wherever `extract_plan` is currently tested) and the extended
`_parse_verdict`.
