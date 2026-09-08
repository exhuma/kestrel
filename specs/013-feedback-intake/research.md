# Phase 0 Research: Feedback Intake

Each item: **Decision**, **Rationale**, **Alternatives considered**. Every
decision below was confirmed directly with the maintainer during an
interactive requirements interview before this plan was written; this
document records the reasoning, not open questions.

## R1. Trigger mechanism: explicit marker, not implicit "all new comments"

**Decision**: Kestrel only acts on a comment/review containing a
configurable trigger token (default `@kestrel`). Anything else is ignored
entirely — never recorded, never acted on.

**Rationale**: A ticket or PR is a shared space where humans discuss with
each other, not just with kestrel. Reacting to every new comment would mean
kestrel joins ordinary human discussion uninvited, and risks a
self-triggering loop if it ever fails to recognize its own output. An
explicit marker is a zero-ambiguity gate: no false positives, no reliance on
perfectly identifying "not kestrel" authorship as the *only* safety net
(FR-005 also gets an author-based backstop — see R6 — but the marker is the
primary gate).

**Alternatives considered**: "All new comments since last-seen" — rejected
as the primary mechanism (too noisy, reacts to side-discussion) though the
underlying "since last-seen" cursor concept is still used *within* the
marker-gated pipeline (R4). Label/review-state-driven triggering (reuse the
existing `trigger_label` convention) was also considered — rejected because
a label is ticket-wide state, awkward for "this specific comment is the
feedback," whereas review state ("changes requested") doesn't apply to plain
ticket comments at all; the marker works uniformly across both surfaces.

## R2. Delivery: webhook where available, poll elsewhere, one convergence point

**Decision**: Extend the existing GitHub webhook (`routers/github_webhook.py`)
with `issue_comment`, `pull_request_review`, and `pull_request_review_comment`
events. Add a poll-based path (`services/feedback/poll.py`) for Jira, GitLab,
and fixture, implementing the existing `PollSource` protocol. Both paths
funnel into one service, `FeedbackIntakeService`.

**Rationale**: GitHub already has a working, HMAC-authenticated inbound path
(constitution v1.4.0's one recorded off-loopback exception) — extending it
with more event *types* on the *same* endpoint and *same* gate costs nothing
new. Jira/GitLab/fixture have no inbound path today (poll-only, per the
project's existing pattern for those sources) and building one is out of
scope for this feature — polling reuses `poll_interval_seconds`, the same
cadence every other signal from those sources already accepts. A single
downstream service, rather than two independent pipelines, is what makes
FR-004 (dedup) and FR-005 (never self-trigger) enforceable in one place
regardless of which transport a piece of feedback arrived through.

**Alternatives considered**: Webhook-only, deferring Jira/GitLab/fixture —
rejected; the maintainer explicitly scoped all three moments (ticket
mid-run, ticket post-run, PR review) as in-scope for this feature, and two
of those three surfaces (Jira RFC comments, fixture comments) have no
webhook option available at all. Poll-only for everything (including
GitHub) was also considered for uniformity — rejected in favor of using the
faster, already-built path where it exists; GitHub still gets a poll
backstop anyway (R2 note below) for missed-delivery recovery, mirroring how
`ReconcileService` already backstops the GitHub *ingestion* webhook the same
way.

## R3. Persistence: durable dedup + durable mid-run queue, one migration

**Decision**: Two new tables — `feedback_item` (external-id primary key,
processing state) and `feedback_cursor` (per ticket/PR, how far read) — plus
one nullable column, `workflow_run.pr_number`. See `data-model.md` for exact
shape.

**Rationale**: `feedback_item.external_id` as a primary key makes
insert-if-absent atomic, so a webhook delivery and a poll cycle racing to
observe the *same* comment can't both act on it — exactly the
`WebhookDeliveryStore`/`DismissalStore` external-id-dedup pattern this
project already uses for the same class of problem. The mid-run queue
(FR-007: hold feedback until the next natural boundary) must survive a
process restart the same way a parked gate already does (`recover`/
`recover_one`) — an in-memory queue like `_Control.replies` cannot. A
separate `feedback_cursor` table (not a column on `workflow_run`) is
required because post-terminal feedback (User Story 4) must be trackable
for a ticket that currently has *no* run at all, and a successor run must
inherit its parent's cursor rather than starting blind.

**Alternatives considered**: No new persistence, deriving "already seen"
from timestamps ("comments newer than the run's last activity") — rejected;
restart and clock-skew edge cases would either re-process a comment (risking
a duplicate action) or silently miss one, both of which directly violate
FR-004/FR-005. Feature 012 deliberately avoided a migration, but that
precedent doesn't generalize here: 012 never needed cross-process-restart
dedup of external events, which is exactly what this feature's core
guarantees depend on.

## R4. Port surface: read + acknowledge, not full comment CRUD

**Decision**: `TaskSource` gains `list_comments(ref, since=None)` and
`acknowledge(feedback, token="eyes")`. `CodeHost` gains
`get_change_request(repo, number)`, `list_review_comments(repo, number,
since=None)`, `acknowledge`, and a pure `change_request_number(url)` helper.
`since` is an opaque, adapter-minted cursor string (GitHub ISO timestamp,
Jira `startAt`, fixture line offset) — the port itself stays ignorant of
each source's pagination scheme.

**Rationale**: Mirrors the existing `TaskSource`/`CodeHost` shape exactly
(`ports.py` already separates "read the current state" from "act on it,"
e.g. `get_task` vs. `post_comment`/`publish_refined`) — this is the same
seam, extended with the one capability it was missing (reading, not just
writing). Keeping `since` opaque avoids leaking GitHub's `since=` param
shape into Jira's `startAt` shape into the port signature.

**Alternatives considered**: A generic "list activity" call spanning
comments, reviews, and status changes uniformly — rejected as premature
generalization; only comments and review feedback are in scope per
`spec.md`, and a broader "activity" concept has no current requirement
driving its shape.

## R5. PR feedback re-entry point: LLM triage, not a fixed step

**Decision**: A cheap turn classifies each piece of review feedback and
picks which pipeline step to resume at — any step is a legal target,
including the two gated ones (`describe`, `refine`).

**Rationale**: Directly required by FR-009/FR-010. Review feedback is not
uniform: "this variable name is unclear" and "this whole approach is wrong"
are both plausible PR comments, and only a semantic read can tell them
apart. Allowing re-entry as far back as a gate (not just autonomous steps)
is necessary because some feedback genuinely does invalidate an already-
approved requirements decision — refusing to ever re-open that would mean
some real feedback is systematically mis-applied downstream of where it
actually belongs.

**Alternatives considered**: Always resume at `code` (cheapest, no new
turn) — rejected: cannot satisfy FR-010, and would silently misapply any
feedback that calls the design or requirements into question as if it were
an implementation nit. Restricting legal re-entry targets to gateless steps
only (`code`/`design`/`gap_analysis`, never re-opening a human gate) was
also considered as a safer middle ground — rejected by the maintainer in
favor of full coverage; a PR comment is allowed to legitimately reopen the
requirements conversation.

## R6. Self-feedback-loop prevention: three independent guards

**Decision**: (1) kestrel never emits the trigger marker in anything it
writes — verified by a test asserting this over every literal comment
template in `notifications.py` and the driver; (2) an author denylist
(`feedback_ignore_authors`, defaulting to kestrel's own configured
identity) plus recognizing GitHub's `user.type == "Bot"`; (3) the
`feedback_item.external_id` primary key caps any loop that somehow evades
(1) and (2) at exactly one iteration, since the second occurrence is a dedup
hit, not a fresh action.

**Rationale**: This is the single most damaging failure mode a
feedback-intake feature could have (kestrel talking to itself indefinitely
on a real ticket), so it gets defense in depth rather than one mechanism.
Each guard independently prevents the failure; only all three failing
simultaneously would allow it, and even then it's bounded to one cycle by
(3).

**Alternatives considered**: Relying on the marker alone (R1) — rejected as
insufficient on its own for this specific risk, since it says nothing about
*authorship*; a marker check answers "is this feedback," not "is this
mine."

## R7. Terminal-state handling: revive vs. successor, per state

**Decision**: `done` → revive the same run if its PR is still open, else
start a linked successor. `escalated` → resume, rebuilding a worktree from
the base branch (no PR exists yet at that point, so there's nothing to
resume onto). `decomposed` → never re-run `gap_analysis`; publish a
single-shot correction task instead.

**Rationale**: Each terminal status left different state behind, so "revive"
means something different for each: `done` has a pushed branch and open PR
to add to; `escalated` deliberately never pushed anything (work was judged
not verified), so there's no branch worth resuming, only the base to retry
from; `decomposed` already published follow-up tasks to the tracker, so
blindly re-running the split risks duplicating what's already there — a
correction is additive, not a replacement.

**Alternatives considered**: Uniform "always start a fresh, linked
successor for any terminal run" — rejected as the general rule: it would
turn every `done` run's feedback into a *disconnected* second PR (the exact
problem User Story 3 exists to solve) instead of amending the existing one.
Uniform "always retry via full re-decomposition" for `decomposed` — rejected
per the maintainer's explicit choice (a correction subtask, not a re-split),
since the first split's tasks are already live on the tracker and a
re-split can't safely account for that without risking duplicates.

## R8. Acknowledgment: reaction, not a comment

**Decision**: Acknowledge receipt via a reaction (e.g. 👀) where the source
supports one; post a real comment only when the resulting work actually
lands (new commits pushed, a revised document produced) — never a "picked
this up" comment.

**Rationale**: Comment fatigue on a real, corporate task-system is a
previously-reported, concrete problem for this project (feature 012's
manual testing surfaced exactly this, fixed via `TaskSourceNotifier.
_last_notified`). Reintroducing a second class of noisy comment here would
regress the same problem this project already spent effort fixing. A
reaction is near-zero-noise and still gives the human immediate visual
confirmation kestrel saw their feedback.

**Alternatives considered**: An explicit "got it" comment plus a completion
comment — rejected outright by the maintainer as doubling comment volume.
No acknowledgment at all — rejected as worse UX than necessary; a reaction
costs nothing extra where the API supports it (GitHub, GitLab), and degrades
gracefully (FR-016) where it doesn't (Jira has no REST v2 reaction endpoint;
fixture is a local file with no reaction concept).
