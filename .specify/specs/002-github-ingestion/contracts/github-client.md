# Contract: GitHubClient additions

New async methods on `app/services/github.py:GitHubClient` (coded to the public
REST API, mirroring the existing `_request` helper at `github.py:47-56`; auth-hint
and token-omission behaviour reused). No secrets in errors (existing `_auth_hint`
never echoes the token).

## `create_issue_comment(repo: str, number: int, body: str) -> str`

- `POST /repos/{repo}/issues/{number}/comments` with `{"body": body}`.
- Returns the comment's `html_url`.
- Raises `GitHubError` on non-2xx (surfaced to the caller, which logs and drops it —
  gate posting is best-effort, FR-026).
- Used only by `GitHubIssueNotifier`. Body is template text + optional deep-link
  (never deliverable content — FR-031).

## `list_issues_by_label(repo: str, label: str, *, state: str = "open") -> list[Issue]`

- `GET /repos/{repo}/issues?labels={label}&state={state}` (paginated; follow `next`
  links until exhausted).
- Returns `Issue` objects (existing dataclass, `github.py:11-17`: `number`, `title`,
  `body`). Pull requests (which the issues API also returns) are filtered out.
- Used by the reconciliation loop (R-10). On error raises `GitHubError`; the loop
  catches, logs, and retries next cycle (FR-014).

## Unchanged / reused

- `get_issue`, `get_default_branch`, `create_pull_request` — unchanged; ingestion
  reuses `get_default_branch` (base branch) and the existing PR path (FR-018).
- Single `github_token` used throughout (auth model unchanged).

## Test contract (httpx mocked — no real GitHub)

- `create_issue_comment` posts to the right path with `{"body": ...}` and returns
  `html_url`; a 404/403 raises `GitHubError` with the auth hint and no token leak.
- `list_issues_by_label` unpaginates correctly and excludes PR entries.
