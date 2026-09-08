# Quickstart: Source Health Checks

## Prerequisites

- Backend running (`cd backend && uv run uvicorn app.main:app --reload`)
  with at least one non-fixture source configured in `config.toml`
  (a Jira or GitHub entry is enough to see a real `unhealthy` transition).
- Frontend running (`cd frontend && npm run dev`).

## Scenario 1 — healthy sources show green on load

1. Start the backend with valid credentials for every configured source.
2. Load the app in a browser.
3. **Expected**: within one `health_check_interval_seconds` cycle (default
   60s) of backend startup, every configured source shows a healthy
   indicator in the app bar. Before the first cycle completes, each shows
   the neutral "not yet known" state — never a false healthy.

## Scenario 2 — a broken credential surfaces automatically

1. With the backend running and every source healthy, edit `config.toml`
   to set a Jira source's token to garbage, and restart the backend (or
   otherwise force the adapter to re-read the bad credential).
2. Wait one background cycle (no user action).
3. **Expected**: the Jira indicator (and only Jira's — GitLab/GitHub, if
   configured, stay healthy) turns unhealthy, visible from any page, with
   no distinction shown between "bad token" and "network unreachable."

## Scenario 3 — manual refresh shortcuts the wait

1. With a source showing unhealthy (Scenario 2), fix the credential in
   `config.toml` (no restart required if the adapter re-reads
   per-request; otherwise restart first).
2. Click the manual refresh control for that source.
3. **Expected**: the indicator updates to healthy well before the next
   scheduled background cycle would have run (SC-002: under 10 seconds).
4. Click refresh again immediately while the first check may still be in
   flight (fast double-click). **Expected**: no duplicate concurrent
   check is started (FR-005) — the UI settles on one consistent result,
   not a flicker between two overlapping checks.

## Scenario 4 — one unresponsive source doesn't stall the others

1. Configure a source pointing at an address that accepts a TCP
   connection but never responds (e.g. a `nc -l` listener, or an
   unreachable internal IP that black-holes instead of refusing).
2. Configure at least one other, healthy source alongside it.
3. Wait for a background cycle.
4. **Expected**: the unresponsive source eventually shows unhealthy (after
   `health_check_timeout_seconds`, default 10s), and the other source's
   result is unaffected and lands on schedule.

## Scenario 5 — fixture-only setup never shows a false negative

1. Run with only a fixture source configured (no Jira/GitHub/GitLab).
2. **Expected**: the fixture indicator shows healthy immediately, with no
   observable network call made for it (nothing to point a proxy/packet
   capture at).
