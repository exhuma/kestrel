# Feature Specification: The coordinator runs the interview

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: Review of Vikunja 710 (2026-09-30). Interviews often asked
different human profiles the same question. Each profile (Product Owner,
Design & Usability, infosec, dba, …) is a kestrel specialist. The developer
decided (2026-09-30):

- The coordinator decides who is interviewed. It uses its understanding of
  the request and each specialist's expertise, and answers can loop in more
  specialists (a persistence answer brings in the dba, perhaps infosec).
  This restores the coordinator-chosen profiles of the old driver (commit
  `d151cb5`, "profile-aware refinement"), which the board rework (026)
  replaced with a fixed trio.
- Every batch of questions goes back to the coordinator before anyone sees
  it. The coordinator removes duplicates, both within the batch and against
  everything already asked, and decides which profile keeps a duplicated
  question. It may only assign, never reword. Code makes sure no question is
  lost.

## Context

Today the interviewers are fixed in code (requester, pm, uiux). Each
persona's questions become a gate as soon as that persona answers, and each
persona advances its own rounds. Nothing compares questions across personas,
and nothing brings another specialist in. The architect, dba, developer,
infosec, ops and qa specialists exist, but none of them can interview.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The right people are asked (Priority: P1)

After CAB-1, the coordinator names the specialists relevant to the request.
Each writes its questions, and the operator answers them per profile. Once a
batch is answered, the coordinator plans again. It can continue with some
specialists (within the round cap), bring in new ones prompted by the
answers, or declare the interview complete, which starts the PRD.

**Acceptance Scenarios**:

1. **Given** CAB-1 is approved, **When** the request continues, **Then** a
   coordinator card plans the interview, and one interview card is created
   per specialist it named.
2. **Given** a batch is answered and an answer touches persistence, **When**
   the coordinator plans again, **Then** it can bring in the dba.
3. **Given** the coordinator names nobody, **When** a batch was answered
   before, **Then** the interview is complete and the PRD starts. **When**
   it is the first plan, **Then** a coordinator review is opened (fail
   closed).
4. **Given** a named specialist that cannot interview, or has used up its
   rounds, **When** the plan is applied, **Then** that specialist is
   ignored.

### User Story 2 - No question is asked twice (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a batch whose question sets share a question, **When** every
   specialist in the batch has drafted, **Then** a coordinator card reviews
   the batch. Each duplicated question is shown to one profile only, in
   one of its original wordings.
2. **Given** a question already asked or answered in an earlier round,
   **When** it is proposed again, **Then** the review can drop it.
3. **Given** a review reply that cannot be read or breaks the rules, **When**
   it arrives, **Then** the question sets are shown unchanged. No question
   is ever lost.
4. **Given** a specialist whose every question was a duplicate, **When** the
   review applies, **Then** its round ends without a gate. In a later round
   it sees the answers given to the other profile.

## Requirements *(mandatory)*

- **FR-001**: Refinement MUST start with an `interview_plan` card for the
  coordinator, not a fixed list of personas.
- **FR-002**: A specialist can interview when its manifest allows
  `refinement`. The plan's envelope MUST list those specialists with their
  label and purpose, plus how many rounds each has used and the cap.
- **FR-003**: Refinement results MUST NOT open gates directly. Once every
  interview card in a batch has drafted or finished, a `question_review`
  card for the coordinator MUST review the batch before any gate opens.
- **FR-004**: The review may only drop a question as a duplicate of a
  question that is kept, or of one already asked earlier. Code MUST
  reject anything else by ignoring the review, never by losing a
  question.
- **FR-005**: Once every gate in a batch is answered, a new plan MUST be
  made. An empty plan completes the interview and MUST start the PRD.
- **FR-006**: A persona's next-round context MUST include the answers to
  its questions that were given to another profile.
- **FR-007**: Each refinement gate MUST name its profile (`gate.persona`),
  and "who acts" MUST name that profile.
- **FR-008**: The coordinator's free-form turns MUST NOT create or move
  these cards.

## Success Criteria *(mandatory)*

- **SC-001**: No question is shown to two profiles in the same request,
  unless the review was ignored.
- **SC-002**: A specialist outside the old trio can be interviewed without
  a code change.

## Assumptions

- A request that was mid-interview when this was deployed continues: when
  its open gates are answered, the whole old interview counts as one batch
  and the coordinator plans the next.
- Rounds are counted per specialist, with the existing cap
  (`board_refinement_round_cap`). The number of rounds is bounded because
  the roster is finite.
