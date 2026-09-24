"""Jira ingestion idempotency + restart recovery (feature 003, US5)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import IntakeOutcome, Workflow
from app.models_workflow import WorkflowRun
from app.persistence.board_store import WorkflowAlreadyExistsError
from app.ports import Task
from app.services.ingestion import BoardIntake, IngestionService
from app.services.jira_poll import JiraPollService
from tests.test_jira_poll import (
    _FakeCodeHost,
    _FakeDismissals,
    _FakeJira,
)


class _FakeTaskSource:
    async def get_task(self, ref):
        return Task(ref=ref, title="t", body="b")

    def visibility(self):
        return "public"


class _RecordingWorkflows:
    """A WorkflowService stand-in that records created runs by task_ref."""

    def __init__(self) -> None:
        self.runs: list[WorkflowRun] = []
        self.sources = {"jira-issue": _FakeTaskSource()}

    def list(self) -> list[WorkflowRun]:
        return self.runs

    async def create(self, repo, issue_number=None, *, source="manual",
                     task_ref=None, base_branch=None) -> str:
        rid = f"wf-{len(self.runs)}"
        self.runs.append(WorkflowRun(
            id=rid, repo=repo, issue_number=issue_number, source=source,
            task_ref=task_ref or f"{repo}#{issue_number}",
        ))
        return rid


class _FakeQuarantine:
    async def intake_for_new_task(self, intake):
        return IntakeOutcome(released=True, safe_content=intake.body)


class _FakeBoard:
    """Records accepted intakes and rejects a repeated (source, task_ref)."""

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


def _poll(jira, wf, dismissals, board=None) -> JiraPollService:
    board = board or _FakeBoard()
    ingestion = IngestionService(
        Settings(_env_file=None),
        wf,
        dismissals,
        BoardIntake(_FakeQuarantine(), board),
    )
    cfg = TaskSourceConfig(
        type="jira", base_url="https://jira.example",
        jql='project = "RFC"', key="RFC", repo_field="cf1",
    )
    return JiraPollService(
        cfg, jira, _FakeCodeHost(), ingestion, dismissals,
    )


@pytest.mark.asyncio
async def test_overlapping_cycles_start_one_run_per_rfc() -> None:
    """Ensure two poll cycles start exactly one run per qualifying RFC."""
    jira = _FakeJira([Task("RFC-1", "t", "b")], fields={"RFC-1": "team/svc"})
    wf, dis = _RecordingWorkflows(), _FakeDismissals()
    board = _FakeBoard()
    poll = _poll(jira, wf, dis, board)
    await poll.run_cycle()
    await poll.run_cycle()  # second cycle observes the same RFC
    assert [c.task_ref for c in board.calls] == ["RFC-1"]


@pytest.mark.asyncio
async def test_restart_with_existing_run_starts_no_duplicate() -> None:
    """Ensure a pre-existing run (survived restart) blocks a new one."""
    jira = _FakeJira([Task("RFC-1", "t", "b")], fields={"RFC-1": "team/svc"})
    wf, dis = _RecordingWorkflows(), _FakeDismissals()
    # Simulate a run rehydrated from the DB after restart.
    wf.runs.append(WorkflowRun(
        id="wf-old", repo="team/svc", issue_number=None,
        source="jira-issue", task_ref="RFC-1",
    ))
    await _poll(jira, wf, dis).run_cycle()
    assert len(wf.runs) == 1  # no duplicate


@pytest.mark.asyncio
async def test_recover_fails_jira_run_in_coding() -> None:
    """Ensure a Jira run in a transient phase is failed loudly on restart."""
    from app.services.workflows import _TRANSIENT, WorkflowService
    from app.storage.registry import SessionRegistry
    from app.storage.workflow_registry import WorkflowRegistry
    from tests.conftest import (
        _FakeGit,
        _FakeGitHub,
        _FakeNotifier,
        _FakeRunner,
    )

    assert "coding" in _TRANSIENT and "verifying" in _TRANSIENT
    reg = WorkflowRegistry()
    reg.create(WorkflowRun(
        id="wf-1", repo="team/svc", issue_number=None, source="jira-issue",
        task_ref="RFC-1", status="coding",
    ))
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=SessionRegistry(), workflows=reg,
        backends=_FakeRunner(SessionRegistry(), []), git=_FakeGit(),
        github=_FakeGitHub(), notifier=_FakeNotifier(),
    )
    await svc.recover()
    assert svc.get("wf-1").status == "failed"
