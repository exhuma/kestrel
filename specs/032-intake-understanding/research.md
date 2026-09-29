# Research: Visible screening and a real understanding step

Engineering decisions for [spec.md](spec.md). The two product decisions were
settled with the developer before the spec was written.

## R1 — Create the request without waking the coordinator

**Decision**: a new `BoardService.create_screening_workflow` creates the
workflow (title = task ref, empty body) and its screening card. It publishes
to the live bus but does **not** fire `on_mutation`, so neither the
coordinator nor dispatch runs on a request that hasn't been screened. The
first real mutation is the end of screening (R3).

**Rationale**: `on_mutation` wakes the coordinator, which would get an LLM
turn over a request with no content, and could propose work before screening
has passed.

## R2 — The screening card

**Decision**: a `security_review` card titled "Screening input", created
`claimed` with no lease and no eligible roles. No specialist can claim it, the
lease sweep never touches it, and the board shows it as in progress in
Intake. The title is a module constant (`SCREENING_TITLE`); that is how the
intake code recognises the card.

## R3 — Ending screening

**Decision**: `BoardService.settle_screening(card_id, state, event_type)` sets
the card to `done` or `cancelled` directly (a system card that never passed
through `review`) and commits once: event, revision bump, bus, and
`on_mutation`. On a pass, the caller has already recorded the title and body
(`BoardStore.record_intake`) and created the understanding card. The single
mutation then wakes the coordinator and dispatches the pm. On a quarantine
the card is cancelled.

## R4 — Quarantine in place

**Decision**: classify through `QuarantineService.intake_for_existing_workflow`
with `workflow=<the new request>` and category `"intake"`. A suspect result
attaches its review card to the same request; the store creates no
placeholder workflow. Existing placeholders (from before this feature) keep
working as before.

## R5 — Release and restart

- **Release**: after `release`, the router schedules
  `IngestionService.continue_intake(workflow_id)` in the background. It acts
  only on a request still awaiting intake (empty body, and a screening card
  but no understanding card). It re-fetches the ticket canonically, then
  records it and starts understanding as in R3. Discard needs nothing more:
  every card is then terminal, so the request is done.
- **Restart**: an existing request whose screening card is still `claimed`,
  and not being screened by this process (an in-memory set), is screened
  again on the next poll.

## R6 — The understanding card

**Decision**: new `CardKind.UNDERSTANDING`, for `pm`, with no workspace. It is
code-only (the coordinator can't create it) and belongs to the
"Understanding" phase. Its result is an `<UNDERSTANDING>…</UNDERSTANDING>`
block. It is stored as a `restatement` reference artifact
(`agent_output`), and the understanding gate is created targeting it. A
missing or empty block opens a coordinator review instead (fail closed).
The logic lives in `services/board/understanding.py`, because `gates.py` is
close to the 500-line limit.

## R7 — Redrafts

**Decision**: on an `understanding_gate` rejection, a new understanding card
is created while the workflow has made fewer than
`1 + board_understanding_redraft_cap` drafts. Otherwise a coordinator review
"Understanding not confirmed after N drafts" is opened. The new setting
defaults to 2 (`GateRequirements.understanding_redraft_cap`). The redraft's
envelope gets the latest rejected gate's restatement and the operator's
correction (the gate's `response` artifact) as extra context. The frontend
requires a correction when rejecting, as it already does for the PRD.

## R8 — Showing the restatement

**Decision**: the action banner shows the understanding gate's target
content inline (fetched like the artifact dialog does), with the existing
Approve and Reject buttons. There is no DTO change: #66's `target_artifact`
already carries the reference.
