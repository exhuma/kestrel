# Feedback intake (feature 013)

A run is never a fire-and-forget dispatch. Once it has started, you can
steer it — from the ticket or the pull/merge request, in whatever tool you
already have open — by leaving a comment that carries kestrel's trigger
marker. This applies across every task source (GitHub, Jira, fixture); the
per-source setup docs ([GitHub](setup-github-workflow.md),
[Jira](setup-jira-workflow.md), [fixture](setup-fixture-workflow.md)) link
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
| `KESTREL_FEEDBACK_WINDOW_DAYS` | `14` | Reserved config knob for a future feedback-recency bound. **Not currently enforced by any behaviour** — set it if you like, but nothing yet reads it to filter or expire feedback. Flagged here so you don't assume it's doing something it isn't. |

Set these as environment variables the same way as any other setting (see
[Configuration](configuration.md#environment-variables)); there is no
per-`[[task_sources]]` override — the marker and guard are shared across
every configured source.

## Where a marked comment can land

- **On the ticket** (a GitHub issue comment, a Jira RFC comment, or a line
  appended to a fixture task's `<slug>.comments.jsonl`) — redirects the run
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

## Acknowledgment (reaction) behaviour, per source

Kestrel best-effort acknowledges a marked comment once it's been queued, so
you get a visible signal it was seen — separate from, and not blocking,
actually processing it (a failed acknowledgment never stops the feedback
from being applied).

| Source | Acknowledgment |
| --- | --- |
| GitHub | An "eyes" (👀) reaction on the triggering comment — an issue comment, a review comment, or a review's own summary comment. |
| GitLab (code host for a Jira- or fixture-sourced run) | An "eyes" award emoji on the triggering review comment. |
| Jira | None — the Jira REST API this integration targets has no comment-reaction endpoint. No reaction ever appears; this is expected, not a bug. |
| Fixture | None — a local file has no reaction concept. |

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
2. An author denylist (`KESTREL_FEEDBACK_IGNORE_AUTHORS`) plus recognizing
   GitHub's own `Bot` account type discards feedback that looks like it
   came from kestrel (or another bot) regardless of what it says.
3. Even if both of those somehow failed, each distinct comment is only
   ever processed once (deduplicated by its own stable id) — so a breach
   is capped at exactly one extra action, never a loop.

If you run kestrel under a dedicated bot account/token, add that account's
name to `KESTREL_FEEDBACK_IGNORE_AUTHORS` as a belt-and-braces measure,
even though guard 1 already means kestrel should never leave a marked
comment in the first place.
