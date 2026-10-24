# Implementation Plan: Task-Source Feedback

**Branch**: `015-task-source-feedback` | **Date**: 2026-09-10
**Spec**: [spec.md](spec.md)

## Summary

Make ticket and review comments the primary decision channel for Kestrel's
non-questionnaire human gates. Extract feedback monitoring into its own port,
make decomposition reviewable before publication, preserve child-task lineage,
and bound monitoring after source closure.

## Technical Context

**Language/Version**: Python 3.12, TypeScript
**Primary Dependencies**: FastAPI, SQLAlchemy, Pydantic, Vue, Vuetify
**Storage**: SQLite with Alembic migrations
**Testing**: pytest and vitest
**Target Platform**: Linux, Docker and run-from-source
**Project Type**: Web application
**Performance Goals**: Complete each poll without blocking unrelated runs.
**Constraints**: Single-user, public task history append-only, no secrets logged.
**Scope**: GitHub, Jira, GitLab review, and fixture sources.

## Constitution Check

- Backend owns decision routing, source lifecycle, and validation.
- Public task sources are append-only; retirement and change summaries are new
  comments, never edits or deletions of public history.
- New persistence is Alembic-owned and every behavior change is test-first.
- Translation is an explicit backing service, selected from configuration; its
  credentials remain environment-backed and are not logged.
- No new frontend-only correctness rule is introduced. The questionnaire stays
  UI-based; all other gates work from the task source.

## Project Structure

```text
backend/app/
├── ports.py
├── config.py
├── config_models.py
├── persistence/
├── services/feedback/
├── services/workflows/
└── services/translation/

backend/tests/
├── test_feedback_*.py
├── test_workflow_*.py
├── test_jira_*.py
└── test_translation_*.py

docs/
├── architecture.md
├── feedback-intake.md
└── setup-*-workflow.md
```

**Structure Decision**: Keep source adapters and workflow orchestration in the
backend. Add reusable feedback and translation service modules outside routers.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| Feedback port | Feedback spans ticket and code-host roles | More polling patches would preserve incorrect boundaries |
| Work graph | Child re-adoption requires durable lineage | Task-reference dedup alone cannot distinguish a reopen |
