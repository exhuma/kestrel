# Feature Specification: A human interview never assumes

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: Review of Vikunja 710 (2026-09-30), marked critical by the
developer. While answering an interview, the page said "This request moved
on while you were answering… Take another look before submitting again",
and a final round said "Last chance to answer before assumptions are
recorded in the PRD". The developer's rule: a human interview must never
assume anything. It stays waiting until a human has responded to every
question.

## Context

- **The 409.** Every intervention carried the request's revision, and any
  change to the request bumped it. The interview page submits one answer set
  per persona, in sequence. The first submission, the coordinator waking
  afterwards, or another persona's turn finishing while the operator typed
  all rejected answers to a question set that was still open and unchanged.
- **The assumptions.** A persona's final interview round was told "do not
  ask further questions… state any remaining assumptions explicitly instead
  of blocking", and the page warned that anything unanswered would become an
  assumption. The pm was told to put "anything still unresolved" under
  assumptions.
- **The backend accepted any answer text.** Only the page required every
  question to have a response. Separately, the revision check was the only
  thing stopping a gate from being decided twice.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - My answers are accepted while the request works (P1)

**Acceptance Scenarios**:

1. **Given** an open interview, **When** other work on the request moves on
   while the operator answers, **Then** submitting succeeds.
2. **Given** a gate already decided (another tab, a double click), **When**
   it is decided again, **Then** it is refused as already decided, in words.

### User Story 2 - Nothing is assumed for me (P1)

**Acceptance Scenarios**:

1. **Given** an interview answer that leaves a question without a response,
   **When** it is submitted, **Then** the backend refuses it and names the
   question. "I don't know — let the PRD state an assumption" and "Not
   relevant" are responses, because the operator chose them.
2. **Given** a persona's final round, **When** it asks, **Then** it is told
   to ask everything it still needs, and never to replace a question with
   an assumption. The page says no further round follows, and that every
   question waits for a response.
3. **Given** the PRD, **When** the pm writes it, **Then** it states an
   assumption only where the operator chose "I don't know", and lists
   anything nobody asked as an open question.

## Requirements *(mandatory)*

- **FR-001**: `resolve_gate` MUST be checked against the gate itself: it
  succeeds while the gate is waiting and undecided, whatever the request's
  revision. Otherwise it is a 409. Other interventions keep the revision
  check.
- **FR-002**: Approving an `answer` gate MUST carry a response to every
  question in the gate's question set. Otherwise it is a 422.
- **FR-003**: No instruction or message may tell an agent or the operator
  that an unanswered question becomes an assumption.

## Success Criteria *(mandatory)*

- **SC-001**: An open interview's answers are never refused because other
  work moved on.
- **SC-002**: No question is recorded without the operator's response.

## Out of scope

- The CAB-1 strategic interview's question cap, which drops questions beyond
  the cap before they are asked. Nothing is assumed for those questions;
  they are never asked.
