# Data Model: Source Health Checks

No new database table (see research.md R5) — this is entirely in-memory,
process-lifetime state.

## `HealthState` (enum)

- `unknown` — no check has completed yet for this entry since the process
  started (FR-009). Never re-enters this state once left.
- `healthy` — the most recent completed check succeeded.
- `unhealthy` — the most recent completed check failed, for any reason
  (network, auth, timeout — FR-002 forbids distinguishing these
  externally).

## `SourceHealth` (in-memory record)

One entry per hand-curated `(label, check_fn)` pair registered at
bootstrap (research.md R6).

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Stable machine id for the entry, e.g. `"github"`, `"jira"`, `"gitlab"`, `"fixture"`. Doubles as the UI label (Title Case at render time) and the `POST /api/health/{name}/refresh` path segment. |
| `state` | `HealthState` | Current status; starts `unknown`. |
| `checked_at` | `datetime \| None` | When `state` last changed away from `unknown`; `None` while still `unknown`. Naive UTC (project convention). |

## `HealthStore` (in-process object)

- Holds `dict[str, SourceHealth]`, keyed by `name`.
- `list_all() -> list[SourceHealth]` — stable order (registration order),
  for both the REST list and each SSE frame.
- `set(name, state) -> None` — updates one entry's `state` and
  `checked_at`, called only by the checking code (background cycle or
  manual refresh), never by a router directly.
- No persistence, no locking beyond what `HealthPollService` itself
  applies per entry (research.md R7) — single-process, asyncio-only
  access, mirroring `NotificationStore`'s in-memory shape but without its
  SQLite backing (notifications must survive restart; health status is
  deliberately not required to).

## Port additions

`backend/app/ports.py`:

```python
class TaskSource(Protocol):
    ...
    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe. Never raises."""

class CodeHost(Protocol):
    ...
    async def check_health(self) -> bool:
        """Best-effort reachability + auth probe. Never raises."""
```

Both return a plain `bool` (not a `HealthState`) — the tri-state
`unknown` is a property of "has this ever been checked," which is
`HealthStore`/`HealthPollService` state, not something an individual
adapter call can express in a single invocation.
