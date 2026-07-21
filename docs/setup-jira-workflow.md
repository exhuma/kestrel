# Jira workflow (feature 003)

Kestrel can ingest change requests (RFCs) from a Jira project and drive them
through the autonomous **refine → PRD approval → design → code → verify → change
request** workflow. Ingestion is **poll-only** — kestrel polls Jira outbound over
HTTPS and exposes **no inbound endpoint**, so no tunnel or reverse proxy is
needed and no off-loopback exception is introduced.

## Configure

Set these in `backend/.env` (see [Configuration](configuration.md) for the full
table). Tokens are secrets — never commit a filled `.env`.

```bash
KESTREL_JIRA_BASE_URL=https://jira.internal.example.com
KESTREL_JIRA_AUTH=basic            # basic (Cloud email+API token) | bearer (Server/DC PAT)
KESTREL_JIRA_EMAIL=you@example.com # basic only
KESTREL_JIRA_API_TOKEN=***         # API token (Cloud) or PAT (Server/DC)
KESTREL_JIRA_PROJECT=RFC           # the RFC project key
KESTREL_JIRA_JQL_FILTER=status = "Ready for Kestrel"   # optional; AND-ed onto project=RFC
KESTREL_JIRA_REPO_FIELD=customfield_10050              # holds owner/name[@base_branch]
KESTREL_JIRA_POLL_INTERVAL_SECONDS=300
```

Kestrel stays agnostic of your Jira conventions: the project key, the qualifying
`JQL` filter, and the repository field name are all configuration.

### Target repository resolution

Each RFC names its target code repository in the configured field
(`KESTREL_JIRA_REPO_FIELD`) as `owner/name` or `owner/name@base_branch`. On each
poll cycle kestrel reads that field and probes the code host for reachability.
If the field is empty or the repo is unreachable, kestrel starts no run and posts
a comment on the RFC asking you to fix the field.

### Code host (self-hostable)

The code lives in a **separate** repository on a code host you configure — a
self-hosted GitLab (or Gitea/Forgejo), or GitHub:

```bash
KESTREL_CODE_HOST=gitlab                                # github | gitlab | gitea
KESTREL_CODE_HOST_BASE_URL=https://gitlab.internal.example.com
KESTREL_CODE_HOST_TOKEN=***                             # PAT for the code host
```

A GitLab code host opens a **merge request**; GitHub opens a **pull request**.
`KESTREL_CODE_HOST=github` reuses `KESTREL_GITHUB_TOKEN` / github.com.

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
verifier will grow to run the modified app and exercise it via real HTTP requests
or Playwright; that behavioural harness is delivered incrementally.)

## The flow, from a human's point of view

1. Create/transition an RFC so it matches the qualifying filter, with the repo
   field set. Kestrel notices it within one poll interval and starts a run.
2. If refinement needs clarification, kestrel posts a **thin** comment on the RFC
   with a deep-link to the kestrel questionnaire — answer there.
3. When the PRD is ready it is **attached** to the RFC (`PRD.md`) and kestrel asks
   for approval (a thin comment + deep-link). Approve or reject in the linked UI.
4. On approval the design → code → verify loop runs autonomously. On success a
   change request is opened and its link is posted to the RFC. On exhaustion the
   run escalates to the RFC.

### Re-running a rejected RFC

Rejecting a PRD (or abandoning a run) records a dismissal so polling won't
silently re-create it. The **re-trigger gesture** is the RFC leaving and
re-entering the qualifying filter (e.g. a status change out of and back into the
JQL): once it no longer qualifies the dismissal is cleared, so re-qualifying it
starts a fresh run.
