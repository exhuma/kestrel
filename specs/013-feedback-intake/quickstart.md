# Quickstart: validating feedback intake

Uses the **fixture** task source (`backend/app/services/fixture.py`, feature
008) for tickets — file-backed, no real GitHub/Jira ticket needed — plus a
real (throwaway) GitHub repo for the PR-review scenarios, since fixture
sources still push real branches/PRs against a configured `code_host`.

## Prerequisites

- `config.toml` has a `[[task_sources]]` fixture entry (see
  `docs/setup-fixture-workflow.md`) and `feedback_marker` left at its
  default (`@kestrel`) or set explicitly.
- Backend running from source, with a `claude` CLI login available — or the
  fake OpenAI-compatible LLM server used to validate feature 012
  end-to-end without spending real tokens (any local text-only backend
  routed at `describe`/`refine`/`gap_analysis`/`design` works identically
  here, since none of those steps need `Capability.FILE_EDITS`).

## Scenario 1 — redirect a parked run from the ticket (US1)

1. Start a run against a fixture task (any ambiguous body works).
2. **Expect**: the run parks at a gate (`awaiting_describe_approval` or
   later `awaiting_refine_approval`) exactly as it does today.
3. Append a line to the fixture task's `<slug>.comments.jsonl` containing
   the trigger marker and corrective feedback (e.g. `"@kestrel actually
   this should also cover X"`).
4. **Expect**: within one poll interval, the run re-parks at the *same*
   gate with a revised deliverable reflecting the feedback — no different
   than manually clicking reject-with-feedback in the UI (spec.md FR-006,
   SC-001).
5. Append a comment **without** the marker.
6. **Expect**: no change to the run at all (spec.md FR-003, SC-006).
7. Re-poll again without adding a new comment.
8. **Expect**: the already-applied comment from step 3 is not re-applied
   (spec.md FR-004).

## Scenario 2 — steer a run with no open gate (US2)

1. Continuing from a run mid-`coding`/`verifying`/`analyzing` (no gate
   open).
2. Append a marked comment to the fixture task's comments file.
3. **Expect**: the in-progress round/turn is not interrupted (spec.md
   FR-007) — confirm by checking the active session isn't terminated
   early.
4. **Expect**: at the next round or step boundary, the feedback is folded
   in (visible in that step's next deliverable or prompt context).

## Scenario 3 — amend the same PR from review feedback (US3)

Requires a real (throwaway) GitHub repo, since this exercises an actual
open PR.

1. Let a run reach `done` (a PR is opened).
2. Leave a marked review comment on that PR requesting an implementation
   change (e.g. `"@kestrel please rename this function"`).
3. **Expect**: within one webhook delivery (or the poll backstop's next
   cycle), new commits appear on the **same** PR — no second PR opened
   (spec.md FR-008, SC-003). The triage turn should have selected `code`.
4. Leave a second marked comment calling the underlying approach into
   question (e.g. `"@kestrel this should use a completely different
   design"`).
5. **Expect**: the run re-enters at `design` (or earlier), and — if that
   step is normally gated — parks awaiting a human decision again (spec.md
   FR-009, FR-010).
6. Check the PR's comment count across steps 2-5.
7. **Expect**: only a reaction on each triggering comment, plus at most one
   "Updated the change request" comment per landed round — comment count
   does not grow proportionally with feedback rounds (spec.md FR-015,
   SC-004).

## Scenario 4 — pick up feedback after a run finished (US4)

1. From Scenario 3's `done` run, merge or close the PR out-of-band (as a
   human reviewer would).
2. Leave a marked comment on the original ticket.
3. **Expect**: a *new* run starts, recorded as linked to the original
   (spec.md FR-011, SC-007) — not a second, disconnected run.
4. Separately, let a run reach `escalated` (exhaust its verify-loop
   iteration cap). Leave marked feedback with guidance on the ticket.
5. **Expect**: the run resumes from its base branch (no PR existed) with
   the feedback folded in (spec.md FR-012).
6. Separately, let a run reach `decomposed`. Leave marked feedback saying
   the split missed something.
7. **Expect**: a new or amended follow-up task appears in the tracker; the
   original run's already-published follow-up tasks are not duplicated
   (spec.md FR-013).

## Regression check

Run an ordinary task through the pipeline end-to-end with **no** feedback
at all and confirm today's existing behavior (feature 003/005/006/012) is
completely unaffected — this feature only adds a new way to *redirect* a
run partway through; it changes nothing about the default path.

Confirm across every scenario above that kestrel's own comments/reactions
(the ones it posts) never themselves trigger a feedback cycle (spec.md
FR-005, SC-005) — the clearest way to check this is confirming the
`feedback_item` table never gains a row whose `author` matches kestrel's own
configured identity.
