# Implementation Plan: OpenCode Permission Compatibility

**Branch**: `007-opencode-permissions` | **Date**: 2026-07-29 |
**Spec**: [spec.md](spec.md)

**Input**: Feature specification for OpenCode 1.18.7 permission compatibility.

## Summary

Replace the obsolete permission-reply request with OpenCode's session-scoped
contract. Treat an event-stream or permission-reply error as a turn failure,
recording it through the existing Kestrel logger and result event rather than
silently abandoning the background permission handler.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, httpx, asyncio

**Storage**: N/A

**Testing**: pytest and pytest-asyncio

**Target Platform**: Linux container and source-run backend

**Project Type**: Web application backend integration

**Performance Goals**: Surface a permission-channel failure immediately rather
than waiting for the ten-minute agent-turn timeout.

**Constraints**: Preserve read-only edit denial; do not add dependencies;
preserve cancellation semantics and existing OpenCode session scoping.

**Scale/Scope**: One adapter module and its unit tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Contract fidelity**: No frontend contract or persisted data changes.
- **Layered backend architecture**: Change remains in the backend adapter,
  with diagnostics using the existing application logger.
- **Test-first discipline**: Add regression tests before adapter changes; all
  backend tests must pass.
- **Deliberate simplicity**: Update the existing adapter without introducing
  configuration, a compatibility layer, or dependencies.
- **Observability**: Permission failures are logged and included in the turn's
  existing error result.

**Gate result (pre-research)**: Pass.

## Project Structure

### Documentation (this feature)

```text
.specify/specs/007-opencode-permissions/
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
backend/
├── app/backends/opencode.py
└── tests/test_opencode_backend.py
```

**Structure Decision**: The existing backend adapter and its focused test
module contain all relevant behavior; no new module is warranted.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations.

**Gate result (post-design)**: Pass. The design keeps failure ownership in the
adapter and uses established result-event and logging paths.
