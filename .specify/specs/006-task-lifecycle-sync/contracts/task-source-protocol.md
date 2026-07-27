# Contract: `TaskSource.transition()` / `supports_time_spent()`

Defined in `backend/app/ports.py`, extending the existing `TaskSource` Protocol
(`ports.py:82-104`). Implemented by `GitHubTaskSource` (`services/github.py:192-219`)
and `JiraTaskSource` (`services/jira.py:144-165`). Async, keyed by the same opaque
`ref: str` the rest of the protocol already uses.

## `LifecycleEvent` (new dataclass, `ports.py`)

```python
@dataclass
class LifecycleEvent:
    kind: Literal["start", "done", "failed", "escalated", "rejected"]
    active_seconds: float | None = None
    wait_seconds: float | None = None
    deep_link: str = ""
```

## `async def transition(self, ref: str, event: LifecycleEvent) -> bool`

- Attempts the platform's native status mechanism for `event.kind` (GitHub: label
  add/remove; Jira: a configured workflow-transition id). If `event.active_seconds is
  not None` and this source's configuration supports a native time field, also writes
  it — but that write's success/failure does **not** affect the return value.
- **Returns `True` iff the *status* aspect of this event was natively applied** — a
  configured mechanism existed for `event.kind` on this source *and* the call
  succeeded. Returns `False` in every other case: no native mechanism exists for this
  platform, no id/label is configured for this specific `event.kind`, or the attempt
  itself failed (network error, expired credential, rate limit — clarified: treated
  identically to "unsupported," no distinct error path).
- The caller (`LifecycleTransitioner`) uses this single bool to decide whether the
  comment-footer fallback needs to carry the status line; it separately checks
  `supports_time_spent()` to decide whether the footer needs the time line — the two
  decisions are independent (a source can apply status natively while still needing
  the footer for time, or vice versa).
- MUST NOT raise on a failed native attempt — internally, any exception from the
  platform's client is caught and treated as "not applied" (`False`), consistent with
  `post_comment`'s existing best-effort-caller convention (`ports.py:89-91`, "best
  effort caller" already documented there).

## `def supports_time_spent(self) -> bool`

- Static per-source capability, not per-call: whether this source has *any*
  configured native field for active time. `GitHubTaskSource` always returns `False`
  (GitHub issues have no time-tracking field at all). `JiraTaskSource` returns `True`
  iff `time_spent_field` is configured non-empty on that source's `TaskSourceConfig`.
- No equivalent method exists for wait-time support — clarified: wait time is always
  footer-only, no platform ever gets a native field for it, so there is nothing to
  query.

## Invariant: `kind` exclusivity (tested)

The caller that builds a `LifecycleEvent` (inside `LifecycleTransitioner`, new
`services/lifecycle.py`) derives `kind` from `run.status` via a single exhaustive,
mutually exclusive mapping:

| `run.status` | `LifecycleEvent.kind` |
|---|---|
| first non-gate active status (existing `run.status = "cloning"` assignment) | `"start"` |
| `"done"` | `"done"` |
| `"failed"` | `"failed"` |
| `"escalated"` | `"escalated"` |
| `"rejected"` | `"rejected"` |

There is no code path that can emit `kind="done"` for a run whose `run.status` is one
of the three failure terminals — this is what FR-002/FR-003 (ticket-facing "done" and
"failure" must never be conflated) reduces to at the protocol boundary.

## Test contract (fake HTTP transport, no live GitHub/Jira calls)

- `GitHubTaskSource.transition()`: asserts the correct label add/remove calls per
  `event.kind`, and the correct `bool` return for a source with `in_progress_label`
  configured (default) vs. one where the operator has emptied the label field (edge
  case: unlikely but must not crash — treated as "no native mechanism," returns
  `False`).
- `JiraTaskSource.transition()`: asserts `transition_issue` is called only when the
  matching `transition_*` field is non-empty; asserts a configured-but-failing
  transition call (mocked 4xx/5xx) returns `False` without raising; asserts
  `time_spent_field` write is attempted independently of the status transition's
  outcome.
- `supports_time_spent()`: `False` always for GitHub; `True`/`False` for Jira matching
  whether `time_spent_field` is set.
- Exhaustive `kind`-mapping test (in `test_lifecycle_transitioner.py`, not the
  per-source test files): for every terminal `run.status`, assert the built
  `LifecycleEvent.kind` matches exactly and that a failed/escalated/rejected run's
  event is never `kind="done"`.
