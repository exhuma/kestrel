# Data Model: Backend Concurrency Cap and Rate-Limit Backoff

**Feature**: 025-backend-concurrency-cap | **Date**: 2026-09-22

No new persisted entities. The only data change is three optional fields on
the existing in-memory backend configuration entity.

## Entity: BackendConfig (existing, extended)

One instance per configured LLM backend, parsed from `config.toml`
`[backends.<id>]` sections at startup.

| Field | Type | Default | Validation | Notes |
|-------|------|---------|------------|-------|
| `type` | str | — | one of `opencode`, `openai_compat`, `claude_cli` | existing |
| `base_url` | str \| None | None | valid URL when set | existing |
| `model` | str \| None | None | — | existing |
| `api_key_env` / other provider fields | … | … | … | existing, unchanged |
| `max_concurrency` | int | `1` | `>= 1` | NEW — in-flight LLM calls admitted for this backend, process-global |
| `rate_limit_retries` | int | `3` | `>= 0` | NEW — max retries after a rate-limit rejection (OpenCode backend) |
| `rate_limit_backoff_seconds` | float | `2.0` | `> 0` | NEW — base delay for exponential backoff when no usable `Retry-After` |

Validation is enforced by Pydantic v2 field constraints at config load; an
invalid value fails startup with the field named (FR-010).

## Runtime state (not persisted)

| State | Owner | Lifetime | Notes |
|-------|-------|----------|-------|
| Concurrency semaphore (`max_concurrency` permits) | one per backend instance, created by the registry at startup | process lifetime | shared by every workflow run and ad-hoc session using that backend; caps are independent per backend (FR-004) |
| Retry counters / backoff state | local to a single `run_turn` call | one turn | no cross-turn memory; each turn starts its retry budget fresh |

## State transitions (per turn, OpenCode backend)

```text
ADMITTED -> CALLING -> (200/ok)      DONE
                 \-> (429, retries left) WAIT(backoff) -> CALLING   (retry n+1)
                 \-> (429, no retries left) FAILED(rate-limit diagnostic)
                 \-> (other error)    FAILED(existing behavior, no retry)
CANCELLED while QUEUED or WAITing -> turn abandoned, slot not consumed
```
