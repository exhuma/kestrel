"""Structured ingestion outcome logging, credentials redacted (US5/FR-035)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.models_board import IntakeOutcome, Workflow
from app.models_workflow import WorkflowRun
from app.persistence.board_store import WorkflowAlreadyExistsError
from app.ports import Task
from app.services.ingestion import BoardIntake, IngestionService


class _TaskSource:
    async def get_task(self, ref):
        return Task(ref=ref, title="t", body="b")

    def visibility(self):
        return "public"


class _Workflows:
    def __init__(self) -> None:
        self.runs: list[WorkflowRun] = []
        self.sources = {
            "jira-issue": _TaskSource(),
            "github-issue": _TaskSource(),
        }

    def list(self):
        return self.runs


class _Dismissals:
    def __init__(self, dismissed=()) -> None:
        self._d = set(dismissed)

    def is_dismissed(self, ref):
        return ref in self._d

    def all(self):
        return list(self._d)


class _Quarantine:
    async def intake_for_new_task(self, intake):
        return IntakeOutcome(released=True, safe_content=intake.body)


class _Board:
    def __init__(self) -> None:
        self.calls = []
        self._seen: set[tuple[str, str]] = set()

    def create_workflow_from_intake(self, intake):
        key = (intake.source, intake.task_ref)
        if key in self._seen:
            raise WorkflowAlreadyExistsError(f"{key[0]}:{key[1]}")
        self._seen.add(key)
        self.calls.append(intake)
        return Workflow(
            id=f"wf-{len(self.calls) - 1}",
            source=intake.source,
            task_ref=intake.task_ref,
            repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility,
            title=intake.title,
        )


def _svc(dismissed=()) -> IngestionService:
    return IngestionService(
        Settings(jira_project="RFC"),
        _Workflows(),
        _Dismissals(dismissed),
        BoardIntake(_Quarantine(), _Board()),
    )


@pytest.mark.asyncio
async def test_started_and_duplicate_outcomes_logged(caplog) -> None:
    """Ensure a started run and a duplicate log distinct outcomes."""
    svc = _svc()
    with caplog.at_level("INFO", logger="kestrel.ingestion"):
        await svc.maybe_start_run(
            source="jira-issue", task_ref="RFC-1", code_repo="team/svc"
        )
        await svc.maybe_start_run(
            source="jira-issue", task_ref="RFC-1", code_repo="team/svc"
        )
    assert "outcome=started RFC-1" in caplog.text
    assert "outcome=skipped-duplicate-board RFC-1" in caplog.text


@pytest.mark.asyncio
async def test_dismissed_and_filtered_outcomes_logged(caplog) -> None:
    """Ensure dismissed + unwatched (GitHub) outcomes are logged."""
    with caplog.at_level("INFO", logger="kestrel.ingestion"):
        await _svc(dismissed={"RFC-9"}).maybe_start_run(
            source="jira-issue", task_ref="RFC-9", code_repo="team/svc"
        )
        # A GitHub source with an unwatched repo is skipped-filtered.
        await _svc().maybe_start_run(
            source="github-issue", task_ref="o/r#5", code_repo="o/r",
            issue_number=5,
        )
    assert "outcome=dismissed RFC-9" in caplog.text
    assert "outcome=skipped-filtered o/r#5" in caplog.text
