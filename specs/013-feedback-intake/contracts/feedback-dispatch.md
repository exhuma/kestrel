# Contract: feedback intake → dispatch pipeline

Covers spec.md FR-003 through FR-007, FR-013, FR-014, FR-015.

## Intake pipeline (`services/feedback/intake.py::FeedbackIntakeService`)

Single convergence point for both transports (webhook and poll — research.md
R2). Every piece of raw feedback, regardless of transport, passes through
this exact sequence:

1. **Marker match** (`marker.py`): case-insensitive, whole-token match of
   `settings.feedback_marker` (default `@kestrel`) in the body. No match →
   **discarded immediately, never persisted** (FR-003 — "never even
   recorded").
2. **Author guard** (research.md R6): body carries the marker but the
   author is in `settings.feedback_ignore_authors`, or (GitHub only)
   `user.type == "Bot"` → discarded, never persisted. This is the second
   independent self-loop guard.
3. **Claim**: `FeedbackStore.claim(external_id)` — an atomic
   insert-if-absent on the `feedback_item` primary key. Already claimed
   (a race between webhook and poll, or a re-delivery) → silent no-op,
   return.
4. **Route to a run**: ticket-origin feedback → the newest run for
   `task_ref` (or none, if the ticket has never had a run — routes to
   nothing yet; out of this feature's scope, since a ticket with no run has
   nothing to redirect). Review-origin feedback → the run whose
   `pr_number == number and repo == repo`, falling back to `pr_url`
   containment for pre-migration rows.
5. Persist the claimed row with `state="queued"`, hand off to
   `FeedbackDispatcher`.
6. **Acknowledge** (best-effort, fire-and-forget, matching
   `TaskSourceNotifier`'s existing fire-and-forget comment-posting shape):
   `source.acknowledge(feedback)`. A `False`/failed acknowledge never blocks
   steps 1-5 having already happened — FR-014's acknowledgment is
   observably separate from whether the feedback was actually processed.

## Dispatch (`services/feedback/dispatch.py::FeedbackDispatcher`)

Branches on the target run's **current** `status` at the moment of dispatch
(not the status when the feedback was authored — a run may have moved on):

| `run.status` | Action | FR |
|---|---|---|
| `awaiting_describe_approval` / `awaiting_refine_approval` | `service.reject(run.id, refinement_prompt=feedback.body)` — the **existing** reject-with-feedback path, unmodified | FR-006 |
| `awaiting_refine_input` (a live questionnaire round) | Stays `queued` — feedback text does not answer structured questions; a human still answers via the existing UI/ticket-reject path once that round completes | FR-007 (queue, don't force-fit) |
| `describing` / `refining` / `analyzing` / `designing` / `coding` / `verifying` / `opening_pr` (transient, no open gate) | Stays `queued`. Consumed by `drain_feedback(service, run)` at exactly two existing boundaries: the top of each `code_and_verify` round, and the top of `continue_run` between steps | FR-007 |
| `done` / `escalated` / `decomposed` (terminal) | Routed to the **triage** path (`contracts/change-request-resume.md`) | FR-011, FR-012, FR-013 |
| `failed` / `rejected` | Stays `queued`, undispatched — these are runs the human already explicitly ended; feedback on them is not auto-resumed (out of this feature's scope; the human already has the reject/delete tools) | — |

`drain_feedback` never interrupts an in-progress agent turn (FR-007's
explicit constraint): it is only ever called at a boundary already reached
by the existing step-completion control flow, never via cancellation of a
live turn.

## Comment-volume contract (FR-015)

- Dispatch through `reject(refinement_prompt=...)` re-enters
  `describe()`/`refine()`'s existing loop, which re-sets the *same*
  `awaiting_*_approval` status the run was already in when the notifier
  last posted about it. `TaskSourceNotifier._last_notified`'s existing
  same-status dedup (shipped for exactly this reason) means this produces
  **zero additional comments** beyond what a normal reject-with-feedback
  cycle already produces today.
- The intake pipeline's own comment posting is limited to: (a) the
  best-effort acknowledgment reaction (not a comment, FR-014), and (b) the
  dispatcher's own single "work landed" comment on completion (FR-015) —
  no "feedback received" comment is ever posted.

## Test contract

- `FeedbackStore.claim` is tested for atomicity under a simulated
  webhook/poll race (two concurrent claims of the same `external_id`;
  exactly one succeeds).
- A parked run + marked ticket comment → `reject` called with the comment
  body as `refinement_prompt`; a *second* identical marked comment on the
  same still-parked run does not re-claim (already-processed row).
- A `coding`-phase run + marked comment → not dispatched to `reject` (no
  gate open); confirmed queued; confirmed consumed at the next
  `code_and_verify` round boundary, not mid-turn.
- An author on `feedback_ignore_authors` (and a GitHub `Bot`-typed author)
  never produces a `feedback_item` row, even with the marker present.
- A comment without the marker never produces a `feedback_item` row.
- Regression: no `post_comment`/notifier call happens purely because
  feedback was picked up (only the acknowledge path fires, and only when
  the source supports it).
