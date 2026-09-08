# Contract: `TaskSource`/`CodeHost` feedback-read port extension

Extends the existing ports (`backend/app/ports.py`) with read + acknowledge
capability, following the exact shape those protocols already use for every
other capability (spec.md FR-001, FR-002, FR-014, FR-016).

## `TaskSource` additions

```python
async def list_comments(
    self, ref: str, since: str | None = None
) -> list[Feedback]:
    """Comments on ref, newest-cursor-forward. since is this adapter's own
    opaque cursor (from a prior call's Feedback items or feedback_cursor),
    or None to read from the beginning."""

async def acknowledge(self, feedback: Feedback, token: str = "eyes") -> bool:
    """Best-effort reaction on the triggering comment. Returns False (never
    raises) when the source has no such capability."""
```

## `CodeHost` additions

```python
async def get_change_request(self, repo: str, number: int) -> ChangeRequest: ...

async def list_review_comments(
    self, repo: str, number: int, since: str | None = None
) -> list[Feedback]:
    """Every reviewer-authored signal on the request: review-body comments
    and inline review comments both surface here, origin="review"."""

async def acknowledge(self, feedback: Feedback, token: str = "eyes") -> bool: ...
```

## Pure helper (no I/O)

```python
def change_request_number(url: str) -> int | None:
    """Extract a PR/MR number from an existing run.pr_url. Used to backfill
    pr_number-less rows with no migration data-fix (data-model.md)."""
```

## Per-implementation behavior

| Source | `list_comments`/`list_review_comments` | `acknowledge` |
|---|---|---|
| GitHub (`services/github.py`) | Issue comments via `GET .../issues/{n}/comments?since=`; review feedback merges `GET .../pulls/{n}/reviews`, review comments, and PR-conversation comments (the issues endpoint) — origin tagged per source in `external_id`'s prefix | Reactions API, endpoint chosen by parsing the `external_id` prefix back out |
| Jira (`services/jira.py`) | `GET /issue/{key}/comment?orderBy=created`, `since` maps to `startAt` | **Always `False`** — no reaction endpoint in REST v2 |
| Fixture (`services/fixture.py`) | Reads `<slug>.comments.jsonl`, `since` is a line offset. **Never** reads `<slug>.log` (that file is this adapter's own `post_comment` sink — reading it back would be a self-feedback loop by construction) | **Always `False`** — no reaction concept for a local file |
| GitLab (`services/gitlab.py`) | MR notes (`GET .../merge_requests/{iid}/notes`) | `POST .../notes/{id}/award_emoji {"name": "eyes"}` |
| gitea | **Not implemented this feature.** `list_review_comments` returns `[]` (degraded, not wrong) — see plan.md's "Not added" note | `False` |

## Test contract

- Each source's contract test (mirroring `test_github_ports.py`/
  `test_jira_client.py`/`test_fixture_task_source.py`'s existing shape)
  asserts: `list_comments`/`list_review_comments` round-trips a `since`
  cursor correctly (a second call with the first call's newest item's
  cursor never re-returns that item); `acknowledge` hits the right
  endpoint where one exists, and returns `False` without raising where one
  doesn't.
- GitHub's `list_review_comments` origin-tagging is tested explicitly: a
  PR-conversation comment and an inline review comment must both surface,
  each `acknowledge`-able via the *correct* underlying endpoint.
- `change_request_number` is tested against a real-shaped URL and a
  malformed/empty one (returns `None`, never raises).
