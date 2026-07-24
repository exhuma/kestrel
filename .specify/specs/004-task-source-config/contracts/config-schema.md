# Contract: `[[task_sources]]` configuration + unified interval

The operator-facing configuration surface. Lives in the TOML file pointed at by
`KESTREL_CONFIG_FILE`. **File-only** (like `backends`); the corresponding env
keys are inert. **Secret-free** — tokens are named, never inlined.

## Top-level keys (changed)

```toml
# One cadence for re-checking every task source (seconds). Replaces the removed
# reconcile_interval_seconds and jira_poll_interval_seconds.
poll_interval_seconds = 300
```

## `[[task_sources]]` — GitHub entry

```toml
[[task_sources]]
type = "github"
watched_repos = ["owner/name"]   # required, non-empty; the ingest/reconcile allow-list
trigger_label = "kestrel"        # optional (default "kestrel")
token_env = "KESTREL_GITHUB_TOKEN"  # optional (this is the default)
```

## `[[task_sources]]` — Jira entry

```toml
[[task_sources]]
type = "jira"
base_url = "https://acme.atlassian.net"   # required
auth = "basic"                            # "basic" (Cloud) | "bearer" (Server/DC PAT)
email = "me@acme.com"                     # basic-auth identity
jql = 'project = "RFC" AND status = "Ready"'  # required; ONE whole query (folds project+filter)
key = "RFC"                               # required; issue-key prefix, used only to scope this source's dismissals
token_env = "KESTREL_JIRA_API_TOKEN"      # optional (default)
# repository resolution (both optional; field tried first, then a matching web link)
repo_field = "customfield_10050"          # optional custom field: owner/name[@base]
repo_link_text = "Repository"             # optional web-link title to match (default)
# code host for resolved repos (self-hostable)
code_host = "github"                      # "github" | "gitlab" | "gitea"
code_host_base_url = ""                   # for gitlab/gitea
code_host_token_env = "KESTREL_CODE_HOST_TOKEN"  # falls back to github token when code_host="github"
```

## Rules

- `type` MUST be `"github"` or `"jira"`. An unknown/missing `type` is a **loud
  config-load error at startup** (never silently skipped).
- A `github` entry MUST have a non-empty `watched_repos`; a `jira` entry MUST
  have `base_url`, `jql`, and `key`. Missing → config error.
- The Jira `key` is the issue-key prefix (e.g. `RFC` for `RFC-123`); it scopes
  which dismissed refs belong to this source (preserving the re-trigger gesture
  after `jira_project` was removed) and is not part of item selection.
- Tokens are NEVER written here — only the **name** of the env var (`*_env`)
  that holds them. A source whose token env is unset produces a **startup
  warning** (cannot authenticate), not a silent no-op or a crash.
- Two entries of the same `type` are allowed; each is polled/listed
  independently.
- **Removed keys** (no longer honoured; a stray `KESTREL_*` is inert):
  `watched_repos`, `trigger_label`, `jira_project`, `jira_jql_filter`,
  `jira_base_url`, `jira_auth`, `jira_email`, `jira_repo_field`,
  `code_host`, `code_host_base_url`, `code_host_token`,
  `reconcile_interval_seconds`, `jira_poll_interval_seconds` (all as top-level
  scalars).

## Behaviour preserved

- Enablement: the GitHub reconcile loop runs iff ≥1 github entry; the Jira poll
  loop(s) run iff ≥1 jira entry. No entries ⇒ no ingestion loop, service still
  starts.
- Webhook acceptance, dedup, dismissal handling, and run creation are unchanged;
  only where the values come from changes (SC-006).
