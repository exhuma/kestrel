# Implementation Plan: Backend Concurrency Cap and Rate-Limit Backoff

**Branch**: `025-backend-concurrency-cap` | **Date**: 2026-09-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/025-backend-concurrency-cap/spec.md`

## Summary

Add a process-global, per-configured-backend concurrency cap (default 1) that
admits LLM turns from all workflow runs and ad-hoc sessions through one shared
limiter per backend instance, and add bounded rate-limit-aware retry to the
OpenCode backend: honor `Retry-After` on HTTP 429, otherwise exponential
backoff with jitter from a configurable base, failing with a concise
rate-limit diagnostic after the configured retries are exhausted. Three new
validated per-backend config fields: `max_concurrency`, `rate_limit_retries`,
`rate_limit_backoff_seconds`.

## Technical Context

**Language/Version**: Python 3.12 (repo standard)

**Primary Dependencies**: FastAPI, Pydantic v2, httpx, asyncio — all already
in use; no new dependencies

**Storage**: N/A (config-only change; SQLite unchanged)

**Testing**: pytest + pytest-asyncio (existing suite under `backend/tests/`)

**Target Platform**: Linux server (single kestrel process)

**Project Type**: web-service (FastAPI backend + Vue frontend; this feature
touches the backend only)

**Performance Goals**: No new latency budget; queueing wait is unbounded by
design (FR-003), provider-call timeouts unchanged

**Constraints**: Constitution quality gates — module ≤ 500 lines, function
complexity ≤ 10 / branches ≤ 12 / args ≤ 5 / statements ≤ 40 / returns ≤ 5 /
locals ≤ 15; no noqa/limit changes; tests first (TDD)

**Scale/Scope**: One kestrel process; a handful of configured backends;
fan-out bounded by workflow design (interview refine = coordinator + N profile
slots per round, plus reconcile/critic turns)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Test-Driven Development (MANDATORY) | PASS | New behavior gets failing tests first: limiter serialization/parallelism/cancellation, retry-after/exponential/exhaustion/no-retry-on-500, config validation. Existing tests must keep passing. |
| II. Code Quality & Simplicity (MANDATORY) | PASS | New logic goes into a small dedicated module (`backends/limiter.py` or similar) plus minimal wiring; no limit changes, no noqa. Re-check after design: `run_turn` in `opencode.py` grows with the retry loop — if complexity threatens the gate, extract a `_post_message_with_retry` helper (planned). |
| III. Security & Robustness (MANDATORY) | PASS | No new external input surface; config values validated at load; backoff jitter prevents thundering herd; no secrets touched. |
| IV. Developer Experience (IMPORTANT) | PASS | `config.toml.example` and `docs/backends.md` / `docs/configuration.md` updated in the same change; quickstart.md documents manual validation. |

**Gate result**: PASS — no violations to justify.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/025-backend-concurrency-cap/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (config contract)
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/app/
├── config_models.py          # BackendConfig: +max_concurrency, +rate_limit_retries, +rate_limit_backoff_seconds (validated)
├── backends/
│   ├── base.py               # unchanged protocol; doc note that run_turn is admission-controlled
│   ├── limiter.py            # NEW: shared per-backend concurrency limiter (asyncio.Semaphore wrapper)
│   ├── opencode.py           # wrap run_turn in limiter; +429 detection, Retry-After/expo backoff retry
│   ├── openai_compat.py      # wrap run_turn in limiter
│   ├── claude_cli.py         # wrap run_turn in limiter
│   └── registry.py           # construct one limiter per configured backend and inject it

backend/tests/
├── test_backend_limiter.py   # NEW: serialization, parallelism, cancellation, independence
├── test_opencode_backend.py  # +429 retry tests (retry-after, exponential, exhaustion, no-retry-on-500)
└── test_config.py            # +validation tests for the three new fields

config.toml.example           # document the three fields with defaults
docs/backends.md              # per-backend concurrency + rate-limit backoff section, Azure example
docs/configuration.md         # new keys under [backends.<id>]
```

**Structure Decision**: Single existing FastAPI backend project; no new
packages. The limiter is a small standalone module so it is unit-testable
without an HTTP stub and reusable by all three backend adapters.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — no violations.
