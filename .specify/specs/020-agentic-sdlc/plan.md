# Implementation Plan: Managed Agentic SDLC

**Branch**: `upstream/main` | **Date**: 2026-09-14
**Spec**: [spec.md](spec.md)

## Summary

Extend Kestrel's existing source-triggered workflow with explicit technical
artifacts, Kestrel-owned deterministic checks, mandatory behavioural evidence,
and a CI continuation loop. Preserve existing PRD and decomposition gates; add
no external agent coordinator.

## Technical Context

**Language/Version**: Python 3.12, TypeScript
**Primary Dependencies**: FastAPI, SQLAlchemy, Vue, Vuetify
**Storage**: SQLite with Alembic migrations
**Testing**: pytest and vitest
**Target Platform**: Linux container and source development
**Project Type**: Web application

## Constitution Check

- Workflow authority and persistence remain in the backend.
- Behaviour changes receive backend and relevant frontend tests.
- Schema changes use Alembic only.
- Existing task-source and code-host ports remain source-neutral.
- New complexity is limited to explicit workflow contracts and result models.

## Design

1. Add an `awaiting_design_approval` gate only if design must be reviewed;
   PRD approval already gates all downstream workflow progression.
2. Extend design output and artifact handover with acceptance, task graph, and
   command-contract files.
3. Execute captured check commands using a backend service before the verifier.
4. Require verifier observations that cover the design-declared boundary.
5. Add code-host CI status retrieval and workflow states for CI waiting, repair,
   and technical readiness.
6. Add source-neutral scheduling and integration-branch behaviour in a later
   increment after the single-task evidence loop is covered end-to-end.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| CI port | CI differs across code hosts | Provider-specific workflow would violate existing port boundary |
