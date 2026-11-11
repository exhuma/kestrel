# Jira workflow

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
verify_ssl = true                      # false ⇒ skip TLS checks on REST/API calls
repo_field = "customfield_10050"       # optional; holds owner/name[@base_branch]
repo_link_text = "Repository"          # web-link title to resolve the repo (default)
change_owner_field = "customfield_10051"  # optional; user field naming the change owner
code_host = "gitlab"                   # github | gitlab | gitea (self-hostable)
code_host_base_url = "https://gitlab.internal.example.com"
# token_env = "KESTREL_JIRA_API_TOKEN"           # default; the API token (Cloud) / PAT
# code_host_token_env = "KESTREL_CODE_HOST_TOKEN"  # default; PAT for the code host
# Where approved tasks become work items (see "Work items" below):
# work_items_project = "DEV"          # unset: sub-tasks of the request
# work_items_issue_type = "Task"      # default: Sub-task, or Task with a project
# work_items_link_type = "Relates"    # request <-> work item, with a project
# work_items_blocks_link_type = "Blocks"
```

```bash
# in backend/.env — only the tokens live in the environment:
KESTREL_JIRA_API_TOKEN=***    # API token (Cloud) or PAT (Server/DC)
KESTREL_CODE_HOST_TOKEN=***   # PAT for a self-hosted code host
```

Kestrel stays agnostic of your Jira conventions: the whole `jql` query and the
repository resolution are configuration. You write the entire JQL (there is no
separate project key).

Set `deployment = "cloud"` for an `atlassian.net` site. Cloud requests use
REST v3 and render Kestrel's controlled Markdown as Atlassian Document Format
(ADF), including review gates, requested-change summaries, and lifecycle
footers. Jira Server/DC keeps REST v2 and plain-text bodies with
`deployment = "server"`.

### Work items

When CAB-2 approves a breakdown, kestrel creates one work item per approved
task, coding and manual alike, so the plan lives in Jira and not only in
kestrel. Each item carries the task's text, its estimate and a link to the
request in kestrel. A task that must wait for another gets a link of type
`work_items_blocks_link_type` ("Blocks" by default) from the task it waits
for. A comment on the request then lists every task with its item's key.

Where the items go is your choice:

- **Without `work_items_project`** they are sub-tasks of the request, of type
  `work_items_issue_type` ("Sub-task" by default). They inherit the
  request's repository field or link.
- **With `work_items_project`** they are issues in that project, of type
  `work_items_issue_type` ("Task" by default), each linked to the request with
  `work_items_link_type` ("Relates" by default). Jira does not allow sub-tasks
  across projects. This suits an organisation whose intake project is
  cross-cutting and whose delivery work lives in a team's project. Keep that
  project out of `jql`, so kestrel never takes its own work items in as new
  requests.

The status icon checks these names against Jira, so a type or link name your
Jira does not have shows up before a breakdown is approved. If Jira cannot be
reached when the breakdown is approved, kestrel keeps trying, and never creates
an item twice: each item carries a `kestrel-…` label it is found by. Moving
the items' status as the work progresses is not built yet (#64).

### The change owner

`change_owner_field` names the Jira **user** field that holds the person who
decides, for the organisation, whether a request goes ahead (the "change
owner"). Leave it out and kestrel simply has no change owner for that source.
The field is read on every announcement, so a change owner set or changed on
the ticket takes effect at the next comment.

The reporter is whoever Jira says reported the issue; there is nothing to
configure for them.

### Target repository resolution

Each RFC names its target code repository either in the configured
`repo_field` (as `owner/name` or `owner/name@base_branch`) **or** via a
web/remote link on the issue whose title matches `repo_link_text` (default
"Repository") — the field is optional. On each poll cycle kestrel resolves
the repo and probes the code host for reachability. If neither resolves or
the repo is unreachable, kestrel starts no run and only logs it (nothing is
posted on the RFC, since the poll would repeat the comment every cycle).

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
3. From here the RFC tells people when it is their turn (see
   [What the ticket shows](#what-the-ticket-shows)), and they answer **on
   the ticket** with a reply ([Replying on the
   ticket](#replying-on-the-ticket)): confirming the understanding and the
   PRD (the reporter) and relaying the CAB decisions (the change owner).
   Interview questions are answered on kestrel's short forms, reached by a
   link. Watching card state, retrying or reassigning a card and resolving
   a quarantined review stay in the Kestrel UI (the Board), which can also
   answer any gate. A resolved gate, an escalation, an approved PRD (also
   attached as a file), the approved tasks' work items, and a clean
   verification's delivery each post one comment back to the RFC;
   day-to-day card-by-card progress is still Board-only. See
   [Architecture → Specialist dispatch, delivery, and write-back](architecture.md#specialist-dispatch-delivery-and-write-back-spec-026-complete-as-of-t078)
   for the full list of what projects and what doesn't.

This replaces the old fixed driver's `describe → refine →
technical_analysis → design → code → verify` sequence and its native Jira
Sub-task decomposition — removed in the Phase 10 clean break, then rebuilt
on the board's own terms (spec 026 T068/T078): refinement/PRD/decomposition
gates exist again, resolved on the ticket or on the Board. An approved
decomposition (CAB-2) becomes cards inside the request's own workflow, and
each approved task also becomes a work item in Jira (see
[Work items](#work-items)); the RFC gets one comment listing them.

### When the delivered work needs changes

Kestrel does not read comments on a merge request. If you are not happy with
what it delivered, there are two ways to get more work done.

**Request changes**, for feedback on the delivered work itself. Open the
request in kestrel, press **Request changes** and say what should change.
The coder works on it on the same branch, the verifier checks it, and the
same merge request is updated. The button appears once the request is done
and nothing else is open. Kestrel refuses if the merge request has already
been merged or closed.

Each later round shows on the merge request. Kestrel pushes the new commits
and comments with them and the coder's summary of the change; when nothing
needed changing, the comment says so and why. The description has a section
headed **Maintained by kestrel**: what the change implements, each later
round, and the screenshots. Kestrel rewrites only that section, so anything
you write above or below it stays.

**A follow-up ticket**, for something that deserves its own requirements and
gates. Create a new ticket that describes the change and links the merge
request, and in its repository field name the first delivery's branch as
the base:

```
group/project@kestrel/board/wf-043c8473
```

The workflow id is in the first request's address in kestrel, after
`#/requests/`, and the branch is also the source branch of its merge request.
The follow-up goes through the whole pipeline, starts from the first
delivery's code, and opens its own merge request **into that branch**.
Merge the follow-up first. If you merge the first one first and its source
branch is deleted, retarget the follow-up's merge request by hand.

### What the ticket shows

kestrel comments on the ticket whenever a person is needed, so nobody has to
watch the Board. Each comment is short and plain, shows what is being decided,
and ends with a link to the request in kestrel (when `public_base_url` is
set; without it the link is left out). A comment is posted **once**: if Jira
cannot be reached, kestrel keeps the comment and posts it later, without ever
posting it twice.

| When | Comment | Mentions |
| --- | --- | --- |
| The understanding gate opens | The restatement in full, asking to confirm or correct it | the reporter |
| The strategic interview or an interview round opens | How many questions and from which profiles, with a link to the form; nothing is asked on the ticket | the reporter |
| The PRD gate opens | The PRD in full | the reporter |
| CAB-1 opens | "Ready for CAB": the strategic-fit answers | the change owner |
| CAB-2 opens | "Ready for CAB": the executive summary, with totals, risks and the task table | the change owner |
| The PRD is signed off | A short note; the PRD is attached to the ticket as `PRD.md` (`PRD-2.md` when signed off again) | nobody |
| CAB-2 approves the breakdown | Each approved task with its work item's key | nobody |
| The work is delivered | The change request link; the ticket should move on | the change owner |
| The request fails, or stops because a decision was rejected | What failed or was rejected; the ticket should move on | the change owner |
| The verifier stops on a problem it may not settle | The problem, and how to clarify it or accept the work | the reporter |
| The verifier flags a policy risk | The risk, and how to clarify it or accept the work | the change owner |
| A clarification was judged | Whether a fix started, or the PRD goes back through sign-off and CAB | nobody |
| CI fails or is repaired; a card is escalated | A plain status line | nobody |

All interview rounds that open together get one comment. If the ticket has no
change owner set, the "ready for CAB" comment says so and nobody is mentioned:
the CAB decision is then taken in the kestrel UI.

**kestrel never changes the status of the ticket.** It does not move, close or
resolve an RFC; where the RFC should move on, it says so in a comment to the
change owner, and moving it stays with its owners. **CAB members are never
mentioned**: kestrel does not know who they are, and only the change owner is
asked to take the decision.

### When a gate is decided

kestrel says what was decided in one plain sentence per gate and outcome.
It says it once, whether the decision was taken on the ticket or in the
kestrel UI:

| Gate | Approved | Rejected |
| --- | --- | --- |
| Understanding | Understanding confirmed. | Understanding corrected, kestrel is rewriting it. |
| CAB-1 | CAB approved the strategic fit. | CAB declined the strategic fit; this request stops here. |
| PRD | PRD signed off. | PRD sent back with feedback, kestrel is revising it. |
| CAB-2 | CAB approved the plan; work starts. | CAB declined the plan. |

When the decision was taken by a reply, the sentence comes in the answer to
that reply, after a thank-you to the person who wrote it.

**Interviews say nothing when they are resolved.** Submitting answers on the
form is not a decision, so a line like "approved" would mislead. The next
comment (the "ready for CAB" comment after the strategic interview, the
next round or the PRD after a refinement) is the acknowledgement.

### Replying on the ticket

Anyone entitled to decide can answer a decision by replying on the ticket
with the reply marker (`@kestrel` by default, see
[`KESTREL_FEEDBACK_MARKER`](configuration.md#environment-variables)) and
what they mean, for example `@kestrel approved`, or `@kestrel no, because
...`. kestrel reads new comments every `board_comment_poll_interval_seconds`
(60 by default) and answers each reply once, mentioning its author.

- **Who decides.** The reporter decides the understanding and the PRD. The
  change owner decides CAB-1 and CAB-2. Both are read from the ticket when
  the reply is read, compared by account. Anyone else is told they cannot
  decide this here, and nothing changes. With no change owner on the ticket
  nobody is entitled to a CAB decision there; it is taken in kestrel.
- **A no needs a reason** for the understanding and the PRD. If a rejection
  has none, or kestrel cannot tell what was meant, it asks again and decides
  nothing.
- **Only replies written after the announcement count.** A reply counts
  only if it was written after kestrel posted the comment announcing that
  gate. Older comments (written before it, or all of a thread's history the
  first time kestrel reads it) are left alone and get no answer. While an
  announcement has not been posted yet (Jira was unreachable and kestrel is
  retrying), nothing written counts either: reply again once the
  announcement is there. kestrel's clock and Jira's are not compared with
  any tolerance, so a badly skewed clock can make a reply that is seconds
  old count late or not at all.
- **Security screening.** Each reply passes the same input screening as a
  new request. A suspicious reply is held: the ticket says so, kestrel acts
  on nothing, and the operator releases or discards it in the kestrel UI.
- **Already decided.** A reply to a gate decided meanwhile (in the UI, or by
  an earlier reply) is told by whom, and never decides the next gate.
- **Interviews** are never answered on the ticket. A reply there gets a
  pointer to the form.
- Names in the audit trail ("Rita Reporter decided via Jira") are the display
  names Jira reported when the reply was read.
- The reply is read only while `comment_sentinel_enabled` is on, because
  kestrel needs its ownership marker to tell its own comments from replies.

### Lifecycle sync

`transition_start`/`transition_done` and `time_spent_field` are still
accepted on a Jira source entry, but nothing currently applies them — see
[Configuration → Lifecycle sync
(currently dormant)](configuration.md#lifecycle-sync-currently-dormant).
kestrel never transitions the RFC itself; moving it stays with its owners.
