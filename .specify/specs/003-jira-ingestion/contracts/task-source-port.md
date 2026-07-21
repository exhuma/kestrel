# Contract: `TaskSource` port

Defined in `backend/app/ports.py`. The **ticket** role: read a ticket, notify on it, attach to
it, publish the approved PRD to it, and enumerate qualifying tickets. Implemented by
`GitHubTaskSource` and `JiraTaskSource` (`services/github.py`, `services/jira.py`). Keyed by an
opaque `ref: str` (GitHub `owner/name#123`; Jira issue key `RFC-123`). All methods are async.

## `Task` dataclass

- `ref: str` — source-native ticket id (also the run's `task_ref`).
- `title: str`, `body: str` — ticket summary and description text.

## `get_task(ref: str) -> Task`

- Fetch the ticket's current title/body. GitHub → `GET /repos/{repo}/issues/{n}`; Jira →
  `GET /rest/api/3/issue/{key}`.
- Raises the source's client error on a missing/unreachable ticket.

## `post_comment(ref: str, body: str) -> str`

- Post a comment; return its URL. Best-effort caller (the notifier) swallows failures (FR-028).
- Body is a fixed template + link only — never PRD/design/plan/questionnaire content (FR-029).

## `attach(ref: str, name: str, content: str) -> None`

- Attach a file (the PRD) to the ticket. GitHub impl MAY no-op (GitHub has no attachment API for
  issues; GitHub uses `publish_refined` instead). Jira →
  `POST /rest/api/3/issue/{key}/attachments` with `X-Atlassian-Token: no-check`.

## `publish_refined(ref: str, content: str) -> None`

- Record the approved PRD on the ticket. GitHub → `update_issue` with the refined body + the
  existing sentinel (preserves `services/workflows.py:752` behaviour). Jira →
  `attach(ref, "PRD.md", content)` (FR-011).

## `list_open(*, project: str | None = None, jql: str | None = None, label: str | None = None) -> list[Task]`

- Enumerate qualifying tickets for the poll/reconcile path. Jira uses `jql`; GitHub uses
  `label` (wraps `list_issues_by_label`). Returns tickets with `ref` populated.

## `deep_link_ref(ref: str) -> str`

- Source-native URL to the ticket (used only for operator logs); MAY return `""`. Distinct from
  the kestrel **gate** deep-link, which stays `public_base_url + /?run={id}` (`notifications.py:109`).

## Test contract (httpx mocked — no real GitHub/Jira)

- `get_task`/`list_open` parse the source's JSON into `Task`.
- `post_comment` returns a URL; a raised transport error is swallowed by the notifier, not the
  caller under test.
- `publish_refined` routes to `update_issue` (GitHub) vs `attach` (Jira).
- No method logs the token/secret (assert redaction).
