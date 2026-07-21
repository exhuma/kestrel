# Contract: `CodeHost` port

Defined in `backend/app/ports.py`. The **repository** role: resolve the base branch, provide
the git remote a worktree provisions from, and open a change request. Implemented by
`GitHubCodeHost` (`services/github.py`, pull request) **and** `GitLabCodeHost`
(`services/gitlab.py`, a **self-hosted GitLab** merge request) — kestrel is self-hostable by
design, so a self-hosted git host is first-class, not deferred (R-03, FR-023a). Gitea/Forgejo is
the same port with different endpoints. The active implementation is chosen by the `code_host`
setting (`github` | `gitlab` | `gitea`) with `code_host_base_url` + `code_host_token`. Keyed by
`repo: str` (`owner/name`, or a GitLab `group/project` path). Async.

## `get_default_branch(repo: str) -> str`

- The repository's default branch, used as the change-request base and the worktree base.
  GitHub → `GET /repos/{repo}` `.default_branch`; GitLab → `GET /projects/{id}`
  `.default_branch`.
- Also the **resolution probe**: the Jira poll calls this to confirm the resolved repo is
  reachable on the configured host before starting a run (FR-007).

## `clone_remote(repo: str) -> str`

- The HTTPS git remote the worktree clones/fetches from. GitHub → `f"{git_base}/{repo}.git"`
  (today inline at `services/workflows.py:681`). GitLab → `f"{code_host_base_url}/{repo}.git"`.
  Auth is injected in `GitService._auth` (`services/git.py:48`) using the code host's token —
  extended to accept a per-run remote/token so a self-hosted host works alongside GitHub.

## `open_change_request(repo: str, *, head: str, base: str, title: str, body: str, draft: bool = True) -> str`

- Open the change request and return its URL (stored as `run.pr_url`). GitHub → a draft **pull
  request** via `create_pull_request`. GitLab → a **merge request** via
  `POST /projects/{id}/merge_requests` (draft signalled by a `Draft:` title prefix). The `body`
  is host/source-aware: GitHub-issue runs keep `Closes #{n}`; Jira runs reference the RFC key
  (the ticket lives in Jira, so there is no host `#` to close).

## Test contract (httpx mocked)

- `get_default_branch` returns the branch and, on a 404/unreachable repo, raises — the poll
  turns that into an `unresolved-repo` outcome (no run). Covered for both GitHub and GitLab.
- `open_change_request` returns the URL; body varies by source (`Closes #n` vs RFC key); GitLab
  drafts prefix `Draft:`.
- `clone_remote` composes the host-appropriate remote (`git_base` vs `code_host_base_url`); no
  token ever appears in logs.
- `code_host` selects `GitHubCodeHost` vs `GitLabCodeHost`; a self-hosted type without
  `code_host_base_url`/`code_host_token` warns at startup.
