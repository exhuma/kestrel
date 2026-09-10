# Feature Specification: Local task source cleanup

**Feature Branch**: `master`
**Created**: 2026-09-10
**Status**: Complete

## User Scenarios & Testing

### User Story 1 - Run disposable local tasks (Priority: P1)

An operator can use local task folders beside Jira work in one development
configuration, without retaining old fixture terminology or state.

**Independent Test**: Configure a local task folder and verify its discovered
task reference and source identity use the local naming contract.

### Requirements

- **FR-001**: Local task sources MUST use `local` and `tasks_dir` in
  configuration.
- **FR-002**: Local task references MUST use the `local:` prefix and source
  identity `local-task`.
- **FR-003**: The standard development configuration MUST enable local tasks
  alongside Jira work.
- **FR-004**: Local task reset MUST remove all documented Kestrel development
  persistence while preserving the configured bare repository.
- **FR-005**: The standard development command MUST start both services with a
  matching backend address.

## Success Criteria

- **SC-001**: All current local task operations use only the local naming
  contract.
- **SC-002**: One documented command resets local task and Kestrel development
  state without deleting the bare repository.

## Assumptions

- Fixture configuration and persisted fixture data are intentionally unsupported.
