"""Structured ingestion outcome logging, credentials redacted (US5/FR-035)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.services.ingestion import IngestionService


class _Workflows:
    def __init__(self) -> None:
        self.runs: list[WorkflowRun] = []

    def list(self):
        return self.runs

    async def create(self, repo, issue_number=None, *, source="manual",
                     task_ref=None, base_branch=None):
        rid = f"wf-{len(self.runs)}"
        self.runs.append(WorkflowRun(
            id=rid, repo=repo, issue_number=issue_number, source=source,
            task_ref=task_ref or f"{repo}#{issue_number}",
        ))
        return rid


class _Dismissals:
    def __init__(self, dismissed=()) -> None:
        self._d = set(dismissed)

    def is_dismissed(self, ref):
        return ref in self._d

    def all(self):
        return list(self._d)


def _svc(dismissed=()) -> IngestionService:
    return IngestionService(
        Settings(jira_project="RFC"), _Workflows(), _Dismissals(dismissed)
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
    assert "outcome=skipped-duplicate RFC-1" in caplog.text


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
