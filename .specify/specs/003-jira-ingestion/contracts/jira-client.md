# Contract: `JiraClient` (`services/jira.py`)

Thin `httpx` client over the Jira REST API (no new dependency — `GitHubClient` already uses
`httpx`). Backs `JiraTaskSource`. Auth is `KESTREL_JIRA_AUTH`: `basic` (Cloud —
`httpx.BasicAuth(jira_email, jira_api_token)`) or `bearer` (Server/DC — `Authorization: Bearer
{jira_api_token}`). The token is a secret and is never logged (FR-004). Mirrors `GitHubClient`'s
shape so tests mock the same transport. All methods async.

## `search(jql: str, *, fields: list[str], max_results: int = 50) -> list[Task]`

- `GET /rest/api/3/search/jql?jql=…&fields=…` (falls back to `/rest/api/3/search`). Returns
  qualifying issues as `Task`s (`ref` = issue key). Used by the poll cycle. Bounded page size;
  logs how many were returned (FR-035, no silent truncation).

## `get_issue(key: str) -> Task`

- `GET /rest/api/3/issue/{key}?fields=summary,description`. Description is the ADF/text body.

## `get_field(key: str, field: str) -> str | None`

- Read one field (the repo-resolution field, FR-006). `field` is a field id
  (`customfield_10050`) or a name resolved to an id via `GET /rest/api/3/field`. Returns the
  scalar value or `None` when empty/absent.

## `add_comment(key: str, body: str) -> str`

- `POST /rest/api/3/issue/{key}/comment`; returns the comment URL. Body is a fixed template +
  link only (FR-029).

## `add_attachment(key: str, name: str, content: str) -> None`

- `POST /rest/api/3/issue/{key}/attachments` (multipart, header `X-Atlassian-Token: no-check`).
  Delivers the PRD (FR-011).

## Errors

- Non-2xx raises `JiraError` (parallel to `GitHubError`); the poll cycle logs and continues on
  the next cycle (FR-003); the notifier swallows comment failures (FR-028).

## Test contract (httpx mocked — no real Jira)

- `search` parses issues → `Task`s and honours `fields`/`max_results`.
- `get_field` returns the value / `None` for empty / raises surfaced as `unresolved-repo`.
- `add_comment`/`add_attachment` issue the right verb/path/headers; token redacted in logs.
- `basic` vs `bearer` set the correct auth header/mechanism.
