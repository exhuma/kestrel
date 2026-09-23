# Research: Backend Concurrency Cap and Rate-Limit Backoff

**Feature**: 025-backend-concurrency-cap | **Date**: 2026-09-22

No NEEDS CLARIFICATION items remained in the plan; the research below
resolves the concrete design decisions.

## R1. Where to place the concurrency limiter

**Decision**: One `asyncio.Semaphore` per configured backend instance, owned
by a small dedicated module (`backend/app/backends/limiter.py`) and injected
into each backend adapter by the registry. The semaphore wraps
`run_turn()` in all three adapters (opencode, openai_compat, claude_cli).

**Rationale**:
- The registry already constructs exactly one backend object per configured
  backend ID at startup; a limiter attached to that object is therefore
  process-global across every workflow run and ad-hoc session, which is the
  scope the user explicitly required ("global, not per-workflow").
- A dedicated module keeps the semaphore logic unit-testable without HTTP
  stubs and satisfies Constitution II (small, cohesive modules).

**Alternatives considered**:
- Module-level global dict keyed by backend ID — rejected: implicit shared
  state, harder to test, breaks if two app instances ever coexist in one
  process (e.g. tests).
- Limiting inside the workflow service layer — rejected: ad-hoc sessions
  bypass the workflow service and would escape the cap; the user requires
  them to share it.
- Process-level (cross-process) coordination via SQLite/Redis — rejected as
  out of scope; documented in spec Assumptions.

## R2. Cancellation while queued

**Decision**: Use `async with semaphore:` so a cancelled task releases its
place cleanly; the provider call never starts if the wait is cancelled.

**Rationale**: `asyncio.Semaphore` acquisition is cancellation-safe in
Python 3.12 (a cancelled waiter does not consume the release). This satisfies
FR-005 with no extra machinery.

## R3. Rate-limit detection in the OpenCode backend

**Decision**: Treat an HTTP 429 response from the message POST as a
rate-limit rejection. Additionally, if the provider returns another status
but the error body clearly names rate limiting (e.g. Azure-style
`"code": "429"` / "rate limit exceeded" text), treat it as one too — kept
as a narrow keyword check inside the retry helper.

**Rationale**: The observed Azure throttling surfaces as HTTP 429; the body
check is defensive and stays inside one small helper so complexity gates
hold (Constitution II).

**Alternatives considered**: Retrying all transient errors (5xx) — rejected
by spec FR-009 (only rate-limit rejections are retried).

## R4. Backoff schedule

**Decision**: For attempt `n` (1-based retry number) without a usable
`Retry-After`: wait `base * 2**(n-1)` seconds plus uniform jitter in
`[0, base/2]`. A `Retry-After` header is used only when it parses to a
finite positive number of seconds; otherwise fall back to the exponential
schedule (spec edge case).

**Rationale**: Standard exponential backoff with jitter avoids thundering
herd when several queued turns hit 429 at once; capping jitter at half the
base keeps waits predictable for tests (tests assert ranges, not exact
values).

## R5. Retry loop placement and complexity budget

**Decision**: Extract a private `_post_message_with_retry(...)` helper in
`opencode.py` containing the retry loop; `run_turn` stays thin (limiter wrap
+ call helper + parse result). The 429 classification is its own tiny
function.

**Rationale**: Keeps `run_turn` and the helper under the complexity/branch
gates (Constitution II) and matches the repo's existing private-helper
pattern in this file.

## R6. Config validation

**Decision**: Add three fields to `BackendConfig` (Pydantic v2) with
constraints: `max_concurrency: int = Field(1, ge=1)`,
`rate_limit_retries: int = Field(3, ge=0)`,
`rate_limit_backoff_seconds: float = Field(2.0, gt=0)`. Startup validation
comes for free from Pydantic; the existing config-load path already fails
fast on invalid backend entries (FR-010).

**Rationale**: Matches the file's existing field style and avoids a second
validation mechanism.
