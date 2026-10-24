# Implementation Plan: Offline fixture folders

**Branch**: `master` | **Date**: 2026-09-10 | **Spec**: [spec.md](spec.md)

## Summary

Replace flat fixture files with recursively discovered task folders. Introduce a
local code host for absolute bare repositories and make delivery capability-aware
so an offline run publishes a branch without a change request.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: FastAPI, Pydantic, standard-library subprocesses
**Storage**: Local JSON, Markdown, and filesystem directories
**Testing**: pytest
**Target Platform**: Linux development host
**Constraints**: Offline fixture actions remain root-contained and deterministic.

## Constitution Check

The design preserves backend-owned workflow decisions, keeps fixture sources
private for rerun, adds no dependency, and adds pytest coverage for behavior.
The operator-controlled fixture root and bare repository remain local trust
boundaries; no network credential is used.

## Project Structure

```text
backend/app/services/fixture.py
backend/app/services/fixture_poll.py
backend/app/services/local_code_host.py
backend/app/services/workflows/
backend/tests/test_fixture_task_source.py
backend/tests/test_fixture_poll.py
backend/tests/test_local_code_host.py
tasks/fixtures.yml
docs/setup-fixture-workflow.md
```

**Structure Decision**: Keep filesystem task behavior in the fixture adapter,
Git repository behavior in a dedicated code-host adapter, and wiring in the
workflow bootstrap.
