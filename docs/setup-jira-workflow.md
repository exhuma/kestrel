# Jira workflow (feature 003)

Kestrel can ingest change requests (RFCs) from a Jira project and drive them
through the autonomous **refine → PRD approval → design → code → verify → change
request** workflow. Ingestion is **poll-only** — kestrel polls Jira outbound
over HTTPS and exposes **no inbound endpoint**, so no tunnel or reverse proxy is
needed and no off-loopback exception is introduced.

## Configure

A Jira source is one `[[task_sources]]` entry in `config.toml` (see
[Configuration → Task sources](configuration.md#task-sources)). The token stays
in the environment — never commit a filled `.env`.

```toml
poll_interval_seconds = 300            # how often every source is re-checked

[[task_sources]]
type = "jira"
base_url = "https://jira.internal.example.com"
auth = "basic"                         # basic (Cloud email+API token) | bearer (Server/DC PAT)
email = "you@example.com"              # basic only
jql = 'project = "RFC" AND status = "Ready for Kestrel"'  # the whole query, yours to write
key = "RFC"                            # issue-key prefix; scopes dismissals only
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

### Target repository resolution

Each RFC names its target code repository either in the configured `repo_field`
(as `owner/name` or `owner/name@base_branch`) **or** via a web/remote link on the
issue whose title matches `repo_link_text` (default "Repository") — the field is
optional. On each poll cycle kestrel resolves the repo and probes the code host
for reachability. If neither resolves or the repo is unreachable, kestrel starts
no run and posts a comment on the RFC.

### Code host (self-hostable)

The code lives in a **separate** repository on the code host configured on the
Jira entry — a self-hosted GitLab (or Gitea/Forgejo), or GitHub. A GitLab code
host opens a **merge request**; GitHub opens a **pull request**.
`code_host = "github"` reuses `KESTREL_GITHUB_TOKEN` / github.com.

### Test the configuration

Before letting kestrel act, dry-run the poll to see what each configured source
matches — it lists the work items and resolved repos and starts **no** run:

```bash
uv run python -m app poll
```

### Verify grounding

The verifier weighs measurable evidence — the project's own checks run in the
run's isolated worktree:

```bash
KESTREL_VERIFY_CHECKS=["uv run pytest -q","npm --prefix frontend test"]
KESTREL_MAX_VERIFY_ITERATIONS=3
```

A failing check forces a reject; the failing output is fed back to the coder. On
exhausting the iteration limit the run **escalates** — it posts a comment on the
RFC and stops rather than shipping unverified work. (The design assumes the
verifier will grow to run the modified app and exercise it via real HTTP
requests or Playwright; that behavioural harness is delivered incrementally.)

## The flow, from a human's point of view

1. Create/transition an RFC so it matches the qualifying filter, with the repo
   field set. Kestrel notices it within one poll interval and starts a run.
2. If refinement needs clarification, kestrel posts a **thin** comment on the
   RFC with a deep-link to the kestrel questionnaire — answer there.
3. When the PRD is ready it is **attached** to the RFC (`PRD.md`) and kestrel
   asks for approval (a thin comment + deep-link). Approve/reject in the UI.
4. On approval the design → code → verify loop runs autonomously. On success a
   change request is opened and its link is posted to the RFC. On exhaustion the
   run escalates to the RFC.

### Re-running a rejected RFC

Rejecting a PRD (or abandoning a run) records a dismissal so polling won't
silently re-create it. The **re-trigger gesture** is the RFC leaving and
re-entering the qualifying filter (e.g. a status change out of and back into the
JQL): once it no longer qualifies the dismissal is cleared, so re-qualifying it
starts a fresh run.
