# Feedback intake (features 013 and 015)

A run is never a fire-and-forget dispatch. Once it has started, you can
steer it — from the ticket or the pull/merge request, in whatever tool you
already have open — by leaving a comment that carries kestrel's trigger
marker. This applies across every task source (GitHub, Jira, local); the
per-source setup docs ([GitHub](setup-github-workflow.md),
[Jira](setup-jira-workflow.md), [local tasks](setup-local-tasks.md)) link
here rather than repeating this section three times.

## The trigger marker

Kestrel only ever acts on a comment that contains its **trigger marker** as
a whole word — `"@kestrel please rename this"` matches, but the marker
glued onto other letters on either side (e.g. as part of a longer word)
does not. Everything else is left alone; kestrel does not read
every comment as an instruction, only ones that explicitly call it out.

| Setting | Default | Purpose |
| --- | --- | --- |
| `KESTREL_FEEDBACK_MARKER` | `@kestrel` | The token a comment must contain, whole-word and case-insensitive, to be treated as feedback at all. |
| `KESTREL_FEEDBACK_IGNORE_AUTHORS` | _(empty)_ | Comma-separated author names/logins never treated as feedback, even if marked — see "Kestrel never triggers on itself" below. |
| `KESTREL_FEEDBACK_WINDOW_DAYS` | `14` | Days after a `done` or `escalated` run became terminal that kestrel polls it. |
| `KESTREL_CHILD_TASK_CLOSURE_RETENTION_DAYS` | `183` | Days a closed published child task stays monitored before retirement. |

Set these as environment variables the same way as any other setting (see
[Configuration](configuration.md#environment-variables)); there is no
per-`[[task_sources]]` override — the marker and guard are shared across
every configured source.

## Where a marked comment can land

- **On the ticket** (a GitHub issue comment, a Jira RFC comment, or a line
  appended to a local task's `comments/` directory) — redirects the run
  that ticket started.
- **On the pull/merge request** — a review comment, a review's own summary
  comment, or (GitHub only) an issue-style comment on the PR's conversation
  tab — redirects the run that opened that PR specifically, even if several
  runs share the same originating ticket over time. Reading review comments
  back is wired for a `github` or `gitlab` code host; a `gitea` code host
  does not support it yet.

## What happens once a marked comment lands

Kestrel branches on **what the target run is doing right now**:

- **Parked at a gate** (e.g. awaiting PRD approval) — applied immediately,
  exactly as if you'd clicked "reject with feedback" in the UI. The run
  re-parks at the same gate with a revised deliverable.
- **Mid-step, no gate open** (refining, designing, coding, verifying) —
  queued. Kestrel never interrupts a turn already in flight; the feedback
  is folded in at the next round or step boundary the run reaches on its
  own.
- **Escalated** (the run gave up after exhausting its verify-loop budget) —
  retried from the base branch, with your feedback carried in as guidance
  for the retry.
- **Done** (a PR is already open) — see "Revive vs. successor" below.

## Deciding an external review

Kestrel posts every non-questionnaire approval gate as a numbered review
revision. The post includes a token such as `[kestrel-review:<token>]` and
this response instruction:

> Reply to this review with its token and `@kestrel approve`,
> `@kestrel reject`, or `@kestrel request changes`.

Include the active revision's token when deciding an understanding, PRD, or
decomposition review. Kestrel accepts only a token that belongs to that gate's
current revision. A stale, missing, or unclassified token is ignored without
changing the gate. With a current token, kestrel replies:
`Please reply with approve, reject, or request changes.`

Approval advances the gate. Rejection closes the run. A request for changes
revises the artifact and opens a new revision. The follow-up gives only a
concise requested-changes delta and a link to the canonical artifact; it never
repeats the artifact or includes a review token.

Use the updated artifact attached or linked by the task source as the
canonical version.

The refine interview questionnaire remains UI-only. Its task-source notice
links to Kestrel and asks you to answer the questionnaire there; comments on
that notice cannot approve, reject, or request changes for the interview.

Decomposition is also a gate. Kestrel first proposes technical analysis and
candidate child tasks on the parent task, then waits for approval. It publishes
neither the analysis nor any child task until that proposal is approved.

## Acknowledgment (reaction) behaviour, per source

Kestrel best-effort acknowledges accepted feedback once it is claimed. It
tries a reaction first; when that is unavailable or returns false, it replies
`Acknowledged.` A failed acknowledgment never stops feedback from being
applied.

| Source | Acknowledgment |
| --- | --- |
| GitHub | An "eyes" reaction, otherwise a reply. |
| GitLab (code host for a Jira- or local-sourced run) | An "eyes" award, otherwise a reply. |
| Jira | A reply: the targeted Jira REST API has no comment-reaction endpoint. |
| Local | A local reply: local task files have no reaction concept. |

## Translation and retirement

When an explicitly configured translation service returns a different English
translation for accepted feedback, kestrel preserves the original and replies:

> Automated English translation (may contain mistakes):

The translation is quoted below that warning. Translation is best-effort: an
unavailable or invalid service is logged and never blocks feedback processing.

A published child task remains monitored after its source is closed. After
`child_task_closure_retention_days` (183 days by default, approximately six
months) from the first observed closure, kestrel posts exactly this notice:

> Kestrel has retired this closed child task. Create a new task for further
> work.

Retirement is permanent for that child task: kestrel stops polling it and does
not automatically resume it if it later receives feedback or is reopened.

## Revive vs. successor: what you'll see in the run list for a `done` run

Once a run reaches `done`, a marked comment on either the ticket or its PR
still reaches it — kestrel resolves the PR's actual state before deciding
what to do:

- **PR still open** — the *same* run resumes: the same branch is checked
  out again and new commits land on the *same* PR. No second PR, no new
  entry in the run list — you'll see the existing run's status cycle back
  through its working states and its deliverable update.
- **PR merged or closed** — the ticket has effectively moved on, so kestrel
  starts a **new, linked run** instead of reopening the finished one. This
  new run appears as its own entry in the run list, carrying a reference
  back to the run that produced it (its lineage) — it is not the same run
  reactivating, and the original run's history is left untouched. Treat it
  like a natural follow-up, not a duplicate: it exists specifically because
  the earlier PR could no longer be amended.

## Kestrel never triggers on itself

This is the one failure mode worth understanding as an operator: kestrel
posting a comment that itself contains the trigger marker, which it would
then react to forever. Three independent guards prevent it, so a single
mistake in any one of them isn't enough to cause a loop:

1. Every fixed comment template kestrel itself writes (gate notifications,
   the "change request opened"/"updated" landing comment, lifecycle
   footers, the Jira "couldn't resolve a repository" comment) is checked —
   mechanically, in CI — to never contain the marker.
2. The complete Kestrel review-request framing is ignored regardless of its
   author. This covers Jira service accounts whose identity cannot be inferred
   from configuration, while preserving human token replies. An author
   denylist (`KESTREL_FEEDBACK_IGNORE_AUTHORS`) plus recognizing
   GitHub's own `Bot` account type discards feedback that looks like it
   came from kestrel (or another bot) regardless of what it says.
3. Even if both of those somehow failed, each distinct comment is only
   ever processed once (deduplicated by its own stable id) — so a breach
   is capped at exactly one extra action, never a loop.

If you run kestrel under a dedicated bot account/token, add that account's
name to `KESTREL_FEEDBACK_IGNORE_AUTHORS` as a belt-and-braces measure,
even though guard 1 already means kestrel should never leave a marked
comment in the first place.
