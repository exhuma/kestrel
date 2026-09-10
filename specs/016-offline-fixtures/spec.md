# Feature Specification: Offline fixture folders

**Feature Branch**: `master`
**Created**: 2026-09-10
**Status**: Complete

## User Scenarios & Testing

### User Story 1 - Run an offline task (Priority: P1)

An operator can create a task folder below a local fixture root and run it
without a ticket tracker or hosted code-review service.

**Independent Test**: Poll a nested task folder targeting a local bare
repository and verify that its branch is published there.

1. **Given** a task folder with `task.json`, **When** it is polled, **Then**
   its root-relative folder path identifies the task.
2. **Given** a successful run, **When** delivery completes, **Then** the branch
   is published locally and no change request is opened.

### User Story 2 - Provide fixture feedback (Priority: P1)

An operator can add timestamped Markdown feedback to a task and Kestrel can
post its own timestamped replies without consuming those replies as feedback.

**Independent Test**: Add a human comment and a Kestrel reply, then verify only
the human comment is returned as feedback.

1. **Given** a human Markdown comment, **When** feedback is polled, **Then** it
   is read with its filename timestamp.
2. **Given** a Kestrel-authored comment, **When** feedback is polled, **Then**
   it is excluded without relying on an author name.

### User Story 3 - Operate local fixtures (Priority: P2)

An operator can initialise, inspect, reset, and add comments to local fixtures
through safe task helpers.

**Independent Test**: Use the documented helpers against the example setup and
verify they only operate below the configured fixture root.

## Requirements

### Functional Requirements

- **FR-001**: Each fixture task MUST be a directory containing `task.json`.
- **FR-002**: Fixture references MUST be root-relative directory paths prefixed
  by `fixture:` and discovery MUST be recursive and sorted deterministically.
- **FR-003**: Fixture paths and attachment names MUST remain contained by their
  configured task directory.
- **FR-004**: Human comments MUST be Markdown files under `comments/` named with
  UTC timestamps; Kestrel replies MUST be distinguishable by file naming alone.
- **FR-005**: Fixture attachments and generated children MUST remain inside the
  task folder, with children located below `children/`.
- **FR-006**: Fixture sources MUST support a local code host using absolute bare
  repository paths, default-branch discovery, local clone/push, and no
  credentials.
- **FR-007**: Delivery to a local code host MUST report a locally published
  branch and MUST NOT open a change request or poll reviews.
- **FR-008**: A checked-in local configuration example MUST target
  `/tmp/pyaltiplano.git` on `master`; generated fixture data MUST be ignored.
- **FR-009**: Task helpers MUST safely initialise, list, inspect, reset, add
  comments, and list local branches.

### Key Entities

- **Fixture task folder**: A root-contained task directory with task metadata,
  comments, attachments, and child task folders.
- **Local code host**: The code-host capability for an absolute local bare Git
  repository; it publishes branches but has no change-request capability.

## Success Criteria

- **SC-001**: A nested fixture task is discovered once in stable path order.
- **SC-002**: 100% of Kestrel reply files are excluded from fixture feedback.
- **SC-003**: An offline delivery publishes one branch and creates zero change
  requests.
- **SC-004**: All fixture paths outside the configured root are rejected.

## Assumptions

- Fixture roots and bare repositories are trusted operator-controlled paths.
- Human comment timestamps are UTC and a numeric suffix resolves collisions.
- Existing flat fixture data is disposable and is not migrated.
