# Implementation Plan: Jira GitLab Production Parity

**Branch**: `018-jira-gitlab-parity` | **Date**: 2026-09-10
**Spec**: [spec.md](spec.md)

## Summary

Close source parity gaps by making the shared external-feedback path operate
correctly for Jira tickets and GitLab MRs, including paginated inline MR
discussions. Replace timestamp-only cursor progression with a source-safe
position, and ensure approved Jira child tasks can later enter the workflow.

## Technical Context

**Language/Version**: Python 3.12, TypeScript/Vue 3
**Primary Dependencies**: FastAPI, SQLAlchemy, httpx, Vue, Vuetify
**Storage**: SQLite via Alembic for durable feedback cursor changes
**Testing**: pytest and vitest
**Target Platform**: Linux, Docker, and run-from-source
**Project Type**: Web application
**Performance Goals**: Poll all available MR pages without blocking unrelated
workflows after one source failure.
**Constraints**: Public source history is append-only; feedback is exactly
once; no secrets in logs; no new dependency unless justified.
**Scope**: Jira task-source feedback and child tasks; GitLab MR feedback.

## Constitution Check

- The backend owns source polling, cursor validation, gate routing, and child
  eligibility; the frontend requires no new correctness rule.
- Cursor persistence changes use an Alembic migration and mirror changed
  backend JSON only if an existing UI surface exposes it.
- Tests precede changed behavior, including pagination, equal-time positions,
  duplicate delivery, gate decisions, and Jira child execution.
- GitLab/Jira failures are isolated, structured-logged without credentials,
  and cannot advance a cursor past unprocessed feedback.
- Reuse the existing ports, intake service, and child lineage instead of
  introducing a parallel feedback or task-dispatch mechanism.

## Project Structure

```text
backend/
├── alembic/versions/                 # Feedback cursor migration, if needed
├── app/
│   ├── ports.py                      # Source-safe feedback cursor contract
│   ├── persistence/feedback_store.py # Cursor read/write and validation
│   └── services/
│       ├── gitlab.py                 # Paginated MR, review, and diff feedback
│       ├── jira.py                   # Native runnable Jira child publication
│       ├── jira_poll.py              # Child discovery and eligibility
│       └── feedback/                 # Composite polling and cursor advancement
└── tests/
    ├── test_gitlab_code_host.py      # MR signal and pagination contract
    ├── test_feedback_poll.py         # Cursor safety and exactly-once intake
    ├── test_jira*.py                 # Gate feedback and child execution
    └── test_workflow_gap_analysis.py # Jira child publication integration
```

**Structure Decision**: Keep API translation in the existing Jira/GitLab
adapters. Keep cursor and ordering policy in reusable feedback/persistence
logic, not in a router or individual workflow step.

## Complexity Tracking

- **Source-safe cursor**: Needed because sources paginate and share timestamps.
  A timestamp-only value would skip valid feedback.
- **MR signal normalizer**: Needed because GitLab exposes several review
  surfaces. Reading notes alone would omit inline and review feedback.
