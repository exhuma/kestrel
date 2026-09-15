# Implementation Plan: Reliable Workflow Cleanup

**Branch**: `022-reliable-workflow-cleanup` | **Date**: 2026-09-15 | **Spec**:
[spec.md](spec.md)

**Input**: Feature specification from
`.specify/specs/022-reliable-workflow-cleanup/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Replace branch-only reset with durable, artifact-scoped cleanup. Capture each
workflow-created source, git, and code-host resource as it is created; use
provider-neutral, idempotent cleanup operations to remove it, close it when
deletion is unavailable, or restore the source task's pre-PRD body. Retain only
failed required cleanup artifacts for retry, expose current records in the
workflow detail UI, and remove local workflow state only when polling can safely
start a new full run.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.13; TypeScript 5

**Primary Dependencies**: FastAPI, SQLAlchemy 2, Alembic, Vue 3, Vuetify 4

**Storage**: SQLite via SQLAlchemy, migration-managed by Alembic

**Testing**: pytest, vitest, `task quality`

**Target Platform**: Linux host/container with a browser-based local UI

**Project Type**: Single-user web application

**Performance Goals**: Cleanup reports local operations immediately and waits
only for required configured provider operations.

**Constraints**: Artifact cleanup is idempotent and workflow-scoped; a missing
artifact is success; comments are best effort; no unrelated source resource can
be removed.

**Scale/Scope**: One concurrent user, one workflow with multiple owned
artifacts, across GitHub, Jira, local tasks, and configured code hosts.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Contract fidelity: update backend schemas and matching frontend types together.
- Layering: keep cleanup policy in a backend service/store; adapters own
  provider API calls; schema changes use Alembic.
- Test-first: add failing cleanup and persistence tests before implementation;
  mock all external HTTP and git actions.
- Simplicity: one artifact model/store and small adapter operations rather than
  provider-specific cleanup orchestration.
- Governance: amend the current public-source append-only cleanup restriction
  before enabling restoration/removal of recorded Kestrel-owned artifacts.

**Gate status**: Pass after the documented constitutional amendment. No new
dependency or project is required.

## Project Structure

### Documentation (this feature)

```text
specs/022-reliable-workflow-cleanup/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
```text
backend/
├── alembic/versions/       # schema migrations
├── app/
│   ├── persistence/        # artifact records and stores
│   ├── services/           # adapters and cleanup orchestration
│   ├── services/workflows/ # workflow lifecycle integration
│   ├── routers/            # cleanup/detail response wiring
│   └── schemas.py          # API contract
└── tests/

frontend/
├── src/components/         # workflow dashboard presentation
├── src/services/           # API client
├── src/types/              # mirrored API types
└── tests/
```

**Structure Decision**: Retain the existing FastAPI service/store/adapter layers
and Vue component/type structure. Add only a focused persistence store and
cleanup policy module when the existing workflow reset module would exceed its
single responsibility.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Public-source cleanup write restriction | Cleanup must restore only recorded Kestrel-owned source artifacts for a full rerun. | Leaving published PRDs/comments/children makes cleanup incomplete and changes the next run's input. |
