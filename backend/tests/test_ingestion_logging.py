"""Structured ingestion outcome logging, credentials redacted (US5/FR-035)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.ports import Task
from app.services.ingestion import IngestionService
from tests.intake_doubles import fake_board_intake


class _TaskSource:
    async def get_task(self, ref):
        return Task(ref=ref, title="t", body="b")

    def visibility(self):
        return "public"


class _FakeTaskSources:
    """A minimal ``TaskSourceRegistry`` double."""

    def __init__(self) -> None:
        self.sources = {
            "jira-issue": _TaskSource(),
            "github-issue": _TaskSource(),
        }
        self.code_hosts: dict[str, object] = {}


class _Dismissals:
    def __init__(self, dismissed=()) -> None:
        self._d = set(dismissed)

    def is_dismissed(self, ref):
        return ref in self._d

    def all(self):
        return list(self._d)


def _svc(dismissed=()) -> IngestionService:
    return IngestionService(
        Settings(jira_project="RFC"),
        _FakeTaskSources(),
        _Dismissals(dismissed),
        fake_board_intake(),
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
