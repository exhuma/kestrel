# Fixture workflow (feature 008)

Kestrel can also run the same **refine → PRD approval → design → code →
verify → change request** workflow against a **local, disposable task**
instead of a real GitHub issue or Jira ticket. Use this to test prompt or
config changes, compare backends, or simply retry a run — without creating
any activity on a real tracker. Like Jira, ingestion is **poll-only**: no
inbound endpoint is exposed, so no tunnel or reverse proxy is needed.

A fixture task's only mandatory reference to the outside world is the
code repository its changes are pushed to — kestrel still opens a real
draft change request there for review.

## Configure

A fixture source is one `[[task_sources]]` entry in `config.toml` (see
[Configuration → Task sources](configuration.md#task-sources)):

```toml
poll_interval_seconds = 300            # how often every source is re-checked

[[task_sources]]
type = "fixture"
fixtures_dir = "/path/to/kestrel-fixtures"   # required; one file per task
code_host = "github"                   # github | gitlab | gitea (self-hostable)
code_host_base_url = ""                # for a self-hosted gitlab/gitea
# code_host_token_env = "KESTREL_CODE_HOST_TOKEN"  # default
```

The code-hosting fields work exactly like a Jira source's: pick the code
host your fixture tasks push branches to, and point
`code_host_token_env` at the environment variable holding its token (the
token itself stays in the environment — never in `config.toml`).

## Author a task

Each task is one JSON file directly under `fixtures_dir`. The filename
(minus `.json`) is the task's identity — kestrel uses it to avoid
starting a second run for the same task, and it is what you'll see
referenced in logs and notifications.

```json
{
  "title": "Add a hello endpoint",
  "body": "Add GET /hello returning {\"msg\": \"hello\"}.",
  "code_repo": "you/sandbox-repo",
  "base_branch": "main"
}
```

| Field | Required | Purpose | Default |
| --- | --- | --- | --- |
| `title` | Yes | The task's title, as shown in the workflow list | — |
| `body` | Yes | The task description the refine step starts from | — |
| `code_repo` | Yes | `owner/name` of the repository to push branches to and open a change request against | — |
| `base_branch` | No | Branch to base the work on | the repository's default branch |

Create, edit, and remove these files directly — there is no separate UI
for authoring them. Kestrel reads a task's file fresh every time it uses
it, so an edit between runs (see [Rerun](#rerun) below) always takes
effect immediately, with no restart needed.

## Test the configuration

Before letting kestrel act, dry-run the poll to see what each configured
source matches — it lists the tasks and their target repos and starts
**no** run:

```bash
python -m app poll
```

## The flow, from a human's point of view

1. Drop a task file into `fixtures_dir`. Kestrel notices it within one
   poll interval and starts a run, exactly like any other source.
2. If refinement needs clarification, answer it in the **Workflows** tab
   as usual.
3. When the PRD is ready, approve it in the UI to let design → code →
   verify run.
4. On success a change request is opened against the configured
   repository. On exhaustion the run escalates and stops rather than
   shipping unverified work.

Every comment, PRD attachment, and status update kestrel would normally
post to a ticket instead stays local, next to the task's JSON file — a
fixture task never causes kestrel to contact GitHub or Jira.

## Rerun

Fixture-sourced runs get one capability no GitHub or Jira run has: a
**Rerun** button in the workflow panel. Rerun discards the run's
in-progress branch and session state and immediately starts a fresh run
for the same task — no need to wait for the next poll interval.

This is deliberately **not** available for GitHub- or Jira-sourced runs,
and the button doesn't appear for them: those tickets may already be
visible to other people (a linked comment, a notification email), so
kestrel never rewinds or replaces their history. Abandoning or cleaning
up a GitHub/Jira run still works as before — it just never restarts the
run automatically the way Rerun does for a fixture task.

To retry a fixture task with a change, edit its JSON file, then click
Rerun — the new run picks up the edited title/body immediately.

### Stopping a task from being picked up again

Kestrel starts at most one run per task, so a fixture file that has
already produced a run is left alone on later polls. Deleting or
cleaning up that run (the same actions available for every source) frees
the task to be picked up as new on the next poll — or just remove the
JSON file once you're done with it.
