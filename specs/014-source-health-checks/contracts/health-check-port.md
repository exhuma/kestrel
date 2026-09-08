# Contract: `check_health()` on `TaskSource` / `CodeHost`

## Signature

```python
async def check_health(self) -> bool
```

Present on both `TaskSource` and `CodeHost` (`backend/app/ports.py`).

## Behavior every implementation MUST satisfy

- **Never raises.** Any failure — connection refused, DNS failure, TLS
  error, timeout, HTTP 4xx/5xx, malformed response body — is caught
  internally and reported as `return False`. A caller iterating multiple
  adapters' health MUST be able to call this with no `try`/`except` of
  its own.
- **No required arguments beyond `self`.** The check is about the
  adapter's own reachability/authentication, not about any particular
  repo or ticket — it MUST NOT depend on any specific `ref`/`repo` value
  already being valid or configured.
- **Read-only.** No adapter's implementation may create, modify, or
  delete anything on the remote system purely to answer a health check.
- **Cheap.** Exactly one HTTP round trip per call — no pagination, no
  retries beyond whatever the adapter's normal transport already does
  for any other single request.
- **Fixture adapter returns `True` unconditionally, with no I/O** (FR-012)
  — it has no external dependency to fail.

## Per-adapter implementation (informative — see research.md R2)

| Adapter | Class | Underlying call |
|---|---|---|
| GitHub | `GitHubTaskSource`, `GitHubCodeHost` (both wrap `GitHubClient`) | `GET /user` |
| Jira | `JiraTaskSource` | `GET /myself` |
| GitLab / Gitea | `GitLabCodeHost` | `GET /user` |
| Fixture | `FixtureTaskSource` | none — `return True` |

## What callers MUST NOT do

- MUST NOT inspect the failure to decide *why* — no caller may branch on
  the underlying exception type reaching the UI or any user-facing
  surface (FR-002: only healthy/unhealthy/unknown ever crosses that
  boundary). Internal logging of the real cause (for the operator's own
  server logs, not the UI) is fine and expected for troubleshooting.

## Timeout is the caller's responsibility

`check_health()` itself does not enforce a timeout — the caller
(`HealthPollService`) wraps every invocation in
`asyncio.wait_for(..., timeout=settings.health_check_timeout_seconds)`
(research.md R3), so the bound lives in one place rather than being
duplicated per adapter.
