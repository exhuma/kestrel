# Implementation Plan: Validated LLM Output

**Branch**: `024-validated-llm-output` | **Date**: 2026-09-17
**Spec**: [spec.md](spec.md)

**Input**: Feature specification from `spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Validate required model outputs at their workflow boundaries. Retry invalid
output through a shared bounded correction helper, allowing five total attempts
per required artifact. Keep deterministic fallbacks only where they preserve a
known safe prior result. Filter blank delta lines before document construction.

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, SQLAlchemy, markdown-it-py

**Storage**: SQLite with existing workflow persistence

**Testing**: pytest

**Target Platform**: Linux container and source development

**Project Type**: Web application

**Performance Goals**: Valid first-attempt output adds no model call.

**Constraints**: Five total attempts; no empty required artifact crosses a
workflow boundary; existing 500-line module and complexity limits apply.

**Scale/Scope**: Required workflow artifacts only: understanding, refined PRD,
technical analysis/task proposal, design contract, and verification verdict.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- Workflow authority and validation remain in backend services.
- Every changed behavior has pytest coverage before implementation.
- No persistence schema change is needed: retries are synchronous within an
  active workflow turn and existing transient-run recovery remains authoritative.
- Optional enrichment retains its explicit best-effort behavior.
- The shared helper is narrowly limited to required model artifacts.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
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
├── app/services/workflows/
│   ├── validation.py
│   ├── interview/
│   └── driver/
└── tests/
    ├── test_workflow_gate.py
    ├── test_workflow_gap_analysis.py
    ├── test_workflow_driver.py
    └── test_task_source_notifier.py
```

**Structure Decision**: Put reusable output-validation and correction mechanics
in `validation.py`; keep artifact-specific parsers and workflow transitions at
their existing call sites.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
