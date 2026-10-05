# Jira workflow (feature 003)

Kestrel can ingest change requests (RFCs) from a Jira project into the
**work board** (see [Architecture](architecture.md#the-work-board-spec-026)
for the domain model). Ingestion is **poll-only** — kestrel polls Jira
outbound over HTTPS and exposes **no inbound endpoint**, so no tunnel or
reverse proxy is needed and no off-loopback exception is introduced.

## Configure

A Jira source is one `[[task_sources]]` entry in `config.toml` (see
[Configuration → Task sources](configuration.md#task-sources)). The token stays
in the environment — never commit a filled `.env`.

```toml
poll_interval_seconds = 300            # how often every source is re-checked

[[task_sources]]
type = "jira"
base_url = "https://jira.internal.example.com"
deployment = "server"                 # cloud (ADF/v3) | server (text/v2)
auth = "basic"                         # basic (Cloud email+API token) | bearer (Server/DC PAT)
email = "you@example.com"              # basic only
jql = 'project = "RFC" AND status = "Ready for Kestrel"'  # the whole query, yours to write
key = "RFC"                            # issue-key prefix; scopes dismissals only
verify_ssl = true                      # false ⇒ skip TLS checks on REST/API calls
repo_field = "customfield_10050"       # optional; holds owner/name[@base_branch]
repo_link_text = "Repository"          # web-link title to resolve the repo (default)
code_host = "gitlab"                   # github | gitlab | gitea (self-hostable)
code_host_base_url = "https://gitlab.internal.example.com"
# token_env = "KESTREL_JIRA_API_TOKEN"           # default; the API token (Cloud) / PAT
# code_host_token_env = "KESTREL_CODE_HOST_TOKEN"  # default; PAT for the code host
```

```bash
# in backend/.env — only the tokens live in the environment:
KESTREL_JIRA_API_TOKEN=***    # API token (Cloud) or PAT (Server/DC)
KESTREL_CODE_HOST_TOKEN=***   # PAT for a self-hosted code host
```

Kestrel stays agnostic of your Jira conventions: the whole `jql` query and the
repository resolution are configuration. You write the entire JQL (there is no
separate project key); `key` is only the issue-key prefix used to scope the
re-trigger gesture.

Set `deployment = "cloud"` for an `atlassian.net` site. Cloud requests use
REST v3 and render Kestrel's controlled Markdown as Atlassian Document Format
(ADF), including review gates, requested-change summaries, and lifecycle
footers. Jira Server/DC keeps REST v2 and plain-text bodies with
`deployment = "server"`.

### Target repository resolution

Each RFC names its target code repository either in the configured
`repo_field` (as `owner/name` or `owner/name@base_branch`) **or** via a
web/remote link on the issue whose title matches `repo_link_text` (default
"Repository") — the field is optional. On each poll cycle kestrel resolves
the repo and probes the code host for reachability. If neither resolves or
the repo is unreachable, kestrel starts no run and posts a comment on the
RFC.

The web link must be an **`http(s)://`** URL (Jira rejects `git@…`/`ssh://` in
the link field). Kestrel parses `owner/name` from it, host-aware per the
source's `code_host`: for `github` it takes the first two path segments (so a
deep link like `…/owner/name/issues/5` still resolves to `owner/name`); for
`gitlab`/`gitea` it keeps the subgroup path and truncates a `/-/` tail (so
`…/group/sub/proj/-/merge_requests/2` resolves to `group/sub/proj`). A trailing
`.git` or slash is tolerated. The **clone** still uses the configured
`code_host_base_url` as the host — the web link only supplies the project path.

### Code host (self-hostable)

The code lives in a **separate** repository on the code host configured on the
Jira entry — a self-hosted GitLab (or Gitea/Forgejo), or GitHub. A GitLab code
host opens a **merge request**; GitHub opens a **pull request**.
`code_host = "github"` reuses `KESTREL_GITHUB_TOKEN` / github.com.

Git clone/fetch/push authenticate over HTTPS with the code-host token
(`oauth2:<token>` for GitLab, `x-access-token:<token>` for GitHub) — no SSH and
no interactive/OAuth browser flow, since kestrel runs headless. The GitLab token
therefore needs **`read_repository` + `write_repository`** scope (plus `api` for
opening merge requests).

### Test the configuration

Before letting kestrel act, dry-run the poll to see what each configured source
matches — it lists the work items and resolved repos and starts **no** run:

```bash
uv run python -m app poll
```

### Verify grounding

The `verifier` specialist's design intent is to weigh evidence it observes
itself by exercising the running, modified project directly, rather than
re-running the coder's own checks — durable test coverage is the coder's TDD
responsibility. The board now runs a real automated claim→turn→accept loop
(spec 026 T034), so this is observable end-to-end against a live RFC, not
just an intended contract.

## The flow, from a human's point of view, today

1. Create/transition an RFC so it matches the qualifying filter, with the
   repo field set. Kestrel notices it within one poll interval.
2. Kestrel screens the RFC's content through the fail-closed input-security
   quarantine. Safe content creates a board **Workflow** and its initial
   cards; suspect content instead creates a quarantined security review that
   only an operator can release or discard, in the Kestrel UI.
3. Everything from here — watching card state, answering an
   understanding/refinement/PRD/decomposition gate, retrying or reassigning
   a card, resolving a quarantined review — happens **in the Kestrel UI**
   (the Board), not on the RFC. A resolved gate, an escalation, a published
   child task, an approved PRD, and a clean verification's delivery each
   post one comment back to the RFC; day-to-day card-by-card progress is
   still Board-only. See
   [Architecture → Specialist dispatch, delivery, and write-back](architecture.md#specialist-dispatch-delivery-and-write-back-spec-026-complete-as-of-t078)
   for the full list of what projects and what doesn't.

This replaces the old fixed driver's `describe → refine →
technical_analysis → design → code → verify` sequence and its native Jira
Sub-task decomposition — removed in the Phase 10 clean break, then rebuilt
on the board's own terms (spec 026 T068/T078): refinement/PRD/decomposition
gates exist again, just resolved on the Board rather than as RFC comments,
and a decomposition publishes real child tickets rather than native
Sub-tasks.

### Re-triggering an RFC

The old fixed driver recorded a "dismissal" when a PRD was rejected or a run
abandoned, so polling wouldn't silently re-create it, clearing that
dismissal only once the RFC left and re-entered the qualifying filter. That
dismissal-setting code was removed with the driver and has no board-domain
replacement, so there is currently no dismissal to clear or re-trigger by
cycling the RFC's status.

### Lifecycle sync and operator hooks

`transition_start`/`transition_done`/etc., `time_spent_field`, and
`hooks_dir` are still accepted on a Jira source entry, but nothing currently
applies them — see [Configuration → Lifecycle sync and operator hooks
(currently dormant)](configuration.md#lifecycle-sync-and-operator-hooks-currently-dormant).
kestrel never transitions the RFC itself; moving it stays with its owners.
