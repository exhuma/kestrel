# Feature Specification: Bounded interview rounds and coordinator-routed PRD redrafts

**Feature Branch**: `028-refinement-rounds-cap`

**Created**: 2026-09-28

**Status**: Implemented (2026-09-28)

**Input**: User description: "Multi-round pre-assessment interviews with an agent-aware round cap (GitHub #48), and PRD-rejection revision routed through the coordinator with a capped redraft loop (GitHub #49)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The interview keeps going until the request is actually understood, or a cap stops it (Priority: P1)

Today the pre-assessment interview asks each persona (requester, pm, uiux)
exactly one round of questions, no matter how vague the original request was.
As the operator, when the first round of answers is not enough to pin the
request down, I want the specialists to ask a follow-up round instead of
being forced into drafting a PRD from an incomplete understanding — but I
also want a hard limit, so a request that can never converge fails visibly
instead of interviewing forever.

**Why this priority**: This is the root-cause fix. Everything downstream
(PRD quality, CAB decisions, agent-eligible work) is only as good as the
understanding captured here. Without it, every vague request either produces
a bad PRD or has to be manually kicked back.

**Independent Test**: Can be fully tested by running a workflow through the
refinement phase with a first-round answer that is deliberately incomplete,
confirming a second round of questions is asked, and confirming the workflow
proceeds to PRD drafting once the specialists are satisfied — without
touching PRD rejection/redraft behavior at all.

**Acceptance Scenarios**:

1. **Given** a workflow at the start of refinement, **When** every persona's
   first-round answer leaves the request adequately understood, **Then** the
   workflow proceeds directly to PRD drafting after round 1, exactly as it
   does today.
2. **Given** a persona's first-round answer leaves genuine ambiguity,
   **When** that persona signals it is not yet satisfied, **Then** a second
   round of questions is created for that persona instead of the workflow
   moving on to PRD drafting.
3. **Given** a persona is on its last available round, **When** it is still
   not fully satisfied, **Then** it is required to consolidate: state its
   remaining assumptions explicitly and proceed, rather than blocking the
   workflow indefinitely.
4. **Given** a persona is asking a follow-up round, **When** its question
   envelope is built, **Then** it includes the current round number, the
   configured round cap, and the prior round's question-and-answer content
   for that persona.

---

### User Story 2 - A rejected PRD is triaged by the coordinator, not auto-redrafted forever (Priority: P2)

Today, rejecting a PRD always creates a brand-new PRD card immediately, with
no limit and no judgment about *why* it was rejected. As the operator, when I
reject a PRD with specific feedback, I want that feedback routed to the
coordinator so it can decide whether the feedback is a direct correction (fix
the PRD) or reveals the request was never actually understood (send it back
to the interview). I also want a hard cap on redraft attempts, so an
unconvergeable PRD fails visibly for me to intervene, instead of looping.

**Why this priority**: This depends on User Story 1's round machinery (a
"send it back to the interview" outcome needs rounds to return to), and
matters only once a workflow has reached the PRD stage — a smaller blast
radius than getting the interview itself right, but still closes a real
infinite-loop gap.

**Independent Test**: Can be fully tested by rejecting a PRD with feedback
that is a plain wording correction and confirming the coordinator produces a
direct fix; separately, by rejecting a PRD with feedback that reveals a
misunderstanding and confirming the workflow returns to the interview phase
with a fresh round; and by rejecting the same PRD repeatedly past the cap and
confirming the workflow reaches a clearly surfaced failure state instead of
generating another redraft.

**Acceptance Scenarios**:

1. **Given** a PRD gate is rejected with feedback that reads as a direct
   correction, **When** the coordinator processes the rejection, **Then** the
   PRD is revised to reflect the feedback and re-submitted for approval
   without restarting the interview.
2. **Given** a PRD gate is rejected with feedback that reveals the underlying
   request was misunderstood, **When** the coordinator processes the
   rejection, **Then** the workflow returns to the interview phase with a new
   round of questions for the affected persona(s).
3. **Given** a PRD has already been redrafted the configured maximum number
   of times, **When** it is rejected again, **Then** the workflow enters a
   visible failure state instead of creating another PRD draft, and the
   reason is surfaced to the operator.
4. **Given** a PRD rejection is being processed, **When** the coordinator
   makes its decision, **Then** it has access to the operator's rejection
   feedback text as part of that decision.

### Edge Cases

- What happens when every persona reaches the round cap simultaneously on the
  same round? The workflow proceeds to PRD drafting using whatever
  understanding (including stated assumptions) exists at that point — it must
  never deadlock waiting for a round that will never be created.
- What happens when a persona signals it is satisfied but a sibling persona
  is not? Each persona's round count and satisfaction are tracked
  independently; PRD drafting starts only once every persona is either
  satisfied or has exhausted its round cap.
- What happens when the coordinator's rejection-triage decision is itself
  unparseable or ambiguous? The workflow must fail closed the same way other
  unparseable specialist output does today (escalated for operator review),
  not silently default to either outcome.
- What happens when a PRD rejection sends the workflow back to the interview,
  and that new interview round itself later completes? The existing
  redraft-cap counter is not reset by a return to the interview — the cap
  bounds total PRD attempts for the workflow, not attempts since the last
  interview round.
- What happens when the round cap or redraft cap is configured to its
  minimum (effectively "no follow-up rounds"/"no redrafts")? Behavior must
  degrade exactly to today's one-round, unconditional-single-redraft
  behavior — this feature must not regress the simple case.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow a persona's pre-assessment interview to
  continue for more than one round when that persona's questions have not
  yet been adequately answered.
- **FR-002**: The system MUST enforce a configurable maximum number of
  interview rounds per persona, defaulting to a value consistent with
  today's behavior remaining the common case for well-specified requests.
- **FR-003**: A specialist conducting the interview MUST be told, as part of
  its instructions for that round, the current round number and how many
  rounds remain before the cap is reached.
- **FR-004**: A specialist on its last available round MUST be instructed to
  consolidate — explicitly state any remaining assumptions — rather than ask
  further blocking questions.
- **FR-005**: A specialist MUST be able to signal that its interview is
  complete before the round cap is reached, so satisfied personas do not
  consume rounds they do not need.
- **FR-006**: The system MUST begin PRD drafting only once every persona has
  either signaled completion or exhausted its round cap — it MUST NOT
  deadlock waiting on a round that will not be created.
- **FR-007**: A follow-up interview round's instructions MUST include that
  persona's own prior round(s) of questions and answers, so the specialist is
  not repeating already-answered questions.
- **FR-008**: When a PRD is rejected, the system MUST route the rejection,
  including the operator's feedback text, to the coordinator rather than
  automatically creating a new PRD draft.
- **FR-009**: The coordinator MUST be able to choose, per rejection, between
  revising the PRD directly and returning the workflow to the interview phase
  for a further round of questions.
- **FR-010**: When the coordinator returns a workflow to the interview phase,
  the system MUST create a further interview round consistent with the round
  cap and awareness requirements above (FR-001 through FR-007).
- **FR-011**: The system MUST enforce a configurable maximum number of PRD
  redraft attempts per workflow.
- **FR-012**: When the redraft cap is reached and the PRD is rejected again,
  the system MUST place the workflow in a distinct failure state rather than
  creating another PRD draft, and MUST surface the reason to the operator.
- **FR-013**: If the coordinator's rejection-triage output cannot be
  interpreted, the system MUST escalate for operator review rather than
  silently choosing a default outcome.
- **FR-014**: Existing single-round, single-redraft behavior MUST remain the
  exact outcome when both caps are configured to their minimum values, so
  this feature is a pure extension of current behavior, not a change to it.

### Key Entities *(include if feature involves data)*

- **Interview round**: One persona's pass through the questionnaire for a
  workflow — a question set, the operator's answer, and whether that persona
  considers the interview complete. A persona's interview consists of one or
  more rounds, up to the configured cap.
- **PRD redraft attempt**: One cycle of drafting a PRD, submitting it for
  approval, and (if rejected) the coordinator's resulting triage decision.
  A workflow's PRD has one or more attempts, up to the configured cap.
- **Coordinator rejection decision**: The outcome the coordinator reaches for
  one PRD rejection — either a direct revision to apply, or a signal to
  return the workflow to the interview phase — together with the feedback
  text that produced it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A request whose first interview answers are ambiguous receives
  a second round of clarifying questions instead of producing a PRD drafted
  from an incomplete understanding.
- **SC-002**: No workflow interview or PRD-redraft cycle runs for more than
  its configured cap of rounds/attempts — every workflow either completes or
  reaches a visible failure state within a bounded number of cycles.
- **SC-003**: An operator rejecting a PRD for a simple wording issue sees a
  revised PRD without the workflow re-running the full interview.
- **SC-004**: An operator rejecting a PRD that reflects a genuine
  misunderstanding sees the workflow return to interviewing rather than
  producing another equally-wrong draft.
- **SC-005**: When a workflow exhausts its redraft cap, the operator can tell
  why the workflow stopped without inspecting logs — the reason is visible on
  the workflow itself.

## Assumptions

- The three existing interview personas (requester, pm, uiux) and their
  eligible-role assignment are unchanged by this feature; only how many
  rounds each may take is new.
- "Round cap" and "redraft cap" are workflow-process-wide configuration
  values (operator/deployment-set), not per-workflow or per-persona
  overrides — consistent with how the existing CAB-1 interview question cap
  is configured today.
- The UI surfacing "round N of M" to the operator is explicitly out of scope
  for this feature (tracked separately under the visualisation epic's
  interview workspace); this feature only needs to make that information
  available to the specialist prompt and, at minimum, to the workflow's
  recorded state/events.
- "Adequately answered" / "satisfied" is determined by the specialist itself
  via an explicit completion signal in its output, not by any automated
  content analysis of the answer.
- The coordinator's rejection-triage decision is a single per-rejection
  judgment call (fix vs. re-interview), not a multi-turn negotiation with the
  operator.
