# Feature Specification: Request activity at a glance

**Feature Branch**: `work`

**Created**: 2026-09-29

**Status**: Implemented (2026-09-29)

**Input**: The Vikunja 710 review. "It's currently really hard telling in the
UI whether the task in the system is working/active or idle/waiting." The
developer approved the proposed activity line on 2026-09-29, adding: "surface
error states to avoid incorrectly sticking around in a 'working' state."

## Context

The board already knows every card's state, but it never combines them into
the one thing an operator needs to know: *is anything happening, and if not,
why not?* Two gaps make it worse:

- Some work leaves no trace on the board while it runs: the coordinator's
  turn, and screening's classification. A request can look idle while a model
  is busy on it.
- A failed agent turn (for example a timeout) leaves no trace either, only a
  log line. A request can look fine while nothing will ever move it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Know at a glance whether a request is moving (Priority: P1)

Every request, on the stage board and in its cockpit, shows one activity
line. It is one of: *working* (who is doing what, and for how long), *waiting
for you*, *queued* (ready work nobody has picked up, and for how long),
*problem* (what failed), *stalled* (nothing running, nothing ready, nothing
waiting on you, yet not done), or *done*.

**Independent Test**: drive a request through screening, a pm turn, a gate,
and a failed coordinator turn. At each point the line states the right one of
the six, with the right actor and subject.

**Acceptance Scenarios**:

1. **Given** a specialist is working a card, or the coordinator is taking a
   turn, or input is being screened, **When** the operator looks, **Then** the
   line says *working*, names who and on what, and how long for.
2. **Given** nothing is running and a gate, quarantine or manual task awaits
   the operator, **Then** the line says *waiting for you* and names it.
3. **Given** ready work nobody has claimed, **Then** the line says *queued*
   with how long it has waited, and turns into a warning after 5 minutes.
4. **Given** a card has failed, or the latest thing that happened is a failed
   agent turn, **Then** the line says *problem* and states what failed.
5. **Given** none of the above and the request is not done, **Then** the line
   says *stalled*.

### User Story 2 - Never show "working" when nothing is (Priority: P1)

*Working* is shown only while this kestrel process is actually running
something for the request. A crash, restart or timeout ends it at once.
Failures are recorded on the request, visible in its feed, so they survive a
restart.

**Acceptance Scenarios**:

1. **Given** kestrel restarts mid-turn, **When** the operator looks, **Then**
   the request is not *working*. An interrupted claim or screening shows as
   *stalled*, with what happens next.
2. **Given** a coordinator or specialist turn fails, **Then** a problem event
   is recorded on the request with a safe, short reason, the feed shows it,
   and the line says *problem* until progress resumes.
3. **Given** the same problem repeats on every retry, **Then** it is recorded
   once, not once per retry.

## Requirements *(mandatory)*

- **FR-001**: The listing and the snapshot MUST carry an `activity` for each
  request: its state, and where relevant who (actor), on what (subject), what
  went wrong (detail), and since when. The backend decides it; the frontend
  only phrases it (constitution Principle II).
- **FR-002**: Precedence: working > a failed card > waiting for you > a failed
  turn > queued > done > stalled. A failed turn is retried automatically and
  must not hide a decision waiting on the operator. (Revised during
  implementation after a live run showed a coordinator timeout masking the
  understanding gate.)
- **FR-003**: *Working* MUST come only from live, in-process activity: agent
  turns, the coordinator's turn and screening. It MUST NOT be inferred from a
  stored card state.
- **FR-004**: A failed agent turn (coordinator or card) MUST be recorded as a
  board event with a safe reason. A problem already recorded as the latest
  event MUST NOT be recorded again. Recording a problem MUST NOT wake the
  coordinator.
- **FR-005**: A problem stops being the activity once any later progress
  event is recorded.
- **FR-006**: The stage-board card and the cockpit MUST show the activity
  line, with an animated indicator while working and a warning once queued
  for over 5 minutes.

## Success Criteria *(mandatory)*

- **SC-001**: At every point in a request's life, its activity names one of
  the six states. None is ever blank.
- **SC-002**: After a restart or timeout, no request shows *working* for
  anything that is no longer running.

## Assumptions

- Live activity is process-local and in memory. Kestrel is single-process
  (constitution Principle IV), and losing it on restart is exactly what
  SC-002 needs.
- The 5-minute queued warning is a display threshold, decided in the
  frontend.
