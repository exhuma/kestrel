# Feature Specification: A released request leaves Intake; escalations stay in their phase

**Feature Branch**: `work`

**Created**: 2026-09-30

**Status**: Implemented (2026-09-30)

**Input**: The operator's run, 2026-09-30.
- The request was run with a different model, and its intake was quarantined.
- After the operator released it, the request stayed in "Intake & alignment". It stayed there even though its Discovery interview had already asked questions.
- The card detail showed **Intake**, **Technical analysis** and **Build** all "in progress".
- A long "Coordinator is planning" wait resolved by itself. It is out of scope.

## Context

- **Intake never closed.** A release moved the quarantine's `security_review` card to `ready`. Nothing ever moves that card on:
  - no specialist is eligible for it;
  - recovery ignores it;
  - no code completes it.

  The request's phase is the earliest phase with open work, so the request stayed in Intake for good and could never read as done. The coordinator could also move the card to `claimed` with no lease, which reads as stalled.
- **A second resolve was not a no-op.** The API documents a second resolve as idempotent, but the store resolved the review again. A release after a discard reopened a cancelled card, and a second release continued the intake a second time.
- **Escalations read as Build.** Unparseable output (from the other model) is escalated fail-closed as a `coordinator_review` card. The phase projection mapped that kind to Build, wherever the escalated work was.
- **Early analysis read as Technical analysis.** The coordinator may start `analysis` while the PRD is still pending (T078). That card marked Technical analysis active during Discovery.

## Decisions

- **Releasing completes the review.** The operator's release is the security review's outcome: its card becomes `done`. A discard makes it `cancelled`, as before.
- **Only a pending review is resolved.** Resolving a review that is no longer pending changes nothing. It returns the review as recorded and does not continue the intake again.
- **Existing stuck requests are repaired by the migration.** A released review whose card is still `ready` or `claimed` is completed.
- **An escalation records its source card.** It is placed in that card's phase. The source is followed up a chain of escalations.
- **Floating kinds.** `coordinator_review` and `analysis` are placed by the work around them:
  - An escalation with no source, and any `analysis` card, goes to the earliest phase with other open work.
  - It never goes later than its own kind's phase.
  - With no other open work, it keeps its kind's phase, so a lone escalation still reads as Build.
- **The projection stays display-only.** Placement changes what the board shows, never what runs.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A released request moves on (Priority: P1)

**Acceptance Scenarios**:

1. **Given** a quarantined intake, **When** the operator releases it, **Then** the review card is done and the request continues to understanding. Its Intake step reads done, and the request leaves Intake.
2. **Given** a review already released or discarded, **When** it is resolved again, **Then** nothing changes and the intake is not continued a second time.
3. **Given** a request released before this feature, **When** the database is upgraded, **Then** its review card is done and the request shows in its real phase.

### User Story 2 - Only the actual phase is active (Priority: P1)

**Acceptance Scenarios**:

1. **Given** an interview card whose output could not be read and was escalated, **When** the board is shown, **Then** the escalation counts in Discovery (Pre-assessment), and Build reads "Not reached".
2. **Given** analysis started while the interview is still open, **When** the board is shown, **Then** Technical analysis is not marked active.
3. **Given** analysis after PRD sign-off, or an escalation with nothing else open during Build, **When** the board is shown, **Then** each shows in its own phase, as before.

## Functional Requirements

- **FR-001**: Releasing a pending review completes its card. Discarding cancels it. Either one bumps the request's revision, and a discard records `screening.discarded`.
- **FR-002**: Resolving a review that is not pending is a no-op. The resolve endpoint continues the intake only for a release that this call made.
- **FR-003**: A migration completes the open cards of already-released reviews and adds the escalation's source card.
- **FR-004**: Every escalation created from a specific card records that card.
- **FR-005**: The phase projection places escalations and analysis as described in Decisions. This applies to the current phase, the per-phase statuses and the furthest phase reached.

## Success Criteria

- **SC-001**: A released request never stays in Intake once its understanding work exists.
- **SC-002**: The stepper never marks a phase later than the request's actual work as active because of an escalation or early analysis.

## Assumptions

- The release event itself stays `screening.released`, which the continued intake records, so a release is not logged twice.
- Escalations with no card to point at (CI repair budget, verifier findings) keep the fallback placement.
