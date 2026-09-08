# Jira workflow (feature 003)

Kestrel can ingest change requests (RFCs) from a Jira project and drive them
through the **describe → refine → gap_analysis → design → code → verify →
change request** workflow (see [Architecture](architecture.md) for the full
pipeline). Ingestion is **poll-only** — kestrel polls Jira outbound over HTTPS
and exposes **no inbound endpoint**, so no tunnel or reverse proxy is needed
and no off-loopback exception is introduced.

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

The verifier weighs evidence it observes itself by launching and exercising
the running, modified project — real HTTP requests for an API boundary,
browser-driven interaction for a UI boundary — rather than re-running the
coder's own checks; durable test coverage is the coder's TDD responsibility.
The one applicable knob is the iteration cap:

```bash
KESTREL_MAX_VERIFY_ITERATIONS=3
```

A failing observation forces a reject; the feedback is fed back to the coder.
On exhausting the iteration limit the run **escalates** — it posts a comment
on the RFC and stops rather than shipping unverified work.

## The flow, from a human's point of view

1. Create/transition an RFC so it matches the qualifying filter, with the repo
   field set. Kestrel notices it within one poll interval and starts a run.
2. Kestrel first restates its understanding of the RFC and asks you to confirm
   or correct it (a thin comment + deep-link) — before any clarifying
   question is asked.
3. If refinement needs clarification, kestrel posts a **thin** comment on the
   RFC with a deep-link to the kestrel questionnaire — answer there. The
   questions stay business-altitude: this phase never asks about
   implementation or architecture.
4. When the requirements document is ready it is **attached** to the RFC
   (`PRD.md`) and kestrel asks for approval (a thin comment + deep-link).
   Approve/reject in the UI.
5. On approval, kestrel performs technical analysis and decomposes the
   approved work into one or more independent, self-contained follow-up
   RFCs — each a native Jira **Sub-task** linked to the parent — plus an
   attached technical-analysis summary. The original RFC's run then ends;
   kestrel does not implement it directly.
6. To implement a follow-up sub-task, transition **it** into the qualifying
   filter the same way you would any RFC. Kestrel recognizes it as already
   scoped and starts directly at `design` — no repeat of steps 2-5. From
   there the design → code → verify loop runs autonomously; on success a
   change request is opened and its link is posted to the sub-task RFC, and
   on exhaustion the run escalates to it.

### Scoping `jql` so follow-up sub-tasks aren't picked up on creation

A follow-up sub-task is created without any status/label kestrel controls —
it starts wherever your Jira Sub-task creation defaults land it. **Write
your `jql` so a newly created sub-task does not already qualify** (e.g. keep
the same `status = "Ready for Kestrel"` gate you use for top-level RFCs, so a
sub-task is only picked up once a human deliberately transitions it, exactly
like step 6 above). Kestrel does not inspect issue type or parentage when
matching `jql` — this is operator-authored query scope, the same posture the
project already takes for `hooks_dir` and other operator-configured trust
boundaries (see the constitution's Access model).

### Re-running a rejected RFC

Rejecting a PRD (or abandoning a run) records a dismissal so polling won't
silently re-create it. The **re-trigger gesture** is the RFC leaving and
re-entering the qualifying filter (e.g. a status change out of and back into the
JQL): once it no longer qualifies the dismissal is cleared, so re-qualifying it
starts a fresh run.

### Lifecycle sync

As a run progresses, kestrel can apply configured workflow transitions
(`transition_start`/`transition_done`/etc.) and write active time to a
configured field — every Jira workflow is different, so none of this is
guessed; unset fields fall back to a comment footer. See [Configuration →
Task sources](configuration.md#task-sources) for the fields, and
[Operator hooks](hooks.md) for the escape hatch when your instance needs
a custom transition or action kestrel doesn't natively support.

### Steering a run with feedback

A marked comment (default trigger: `@kestrel`) on the RFC redirects the run
it started — applied immediately if the run is parked at a gate, queued
until the next boundary otherwise. Jira's REST API has no comment-reaction
endpoint, so — unlike GitHub — kestrel does **not** react to the triggering
comment; that's expected, not a missed acknowledgment. Amending the same
merge/pull request from a review comment is supported when the configured
`code_host` is `gitlab` or `github` (via `award_emoji`/reactions
respectively); a `gitea` code host does not yet support reading review
comments back. See [Feedback intake](feedback-intake.md) for the full
behaviour, including what a `done` RFC reactivating vs. a linked successor
run looks like.
