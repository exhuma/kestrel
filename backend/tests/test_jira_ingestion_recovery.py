"""Jira ingestion idempotency + restart recovery (feature 003, US5)."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import AcceptedTaskIntake, IntakeOutcome, Workflow
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


class _FakeTaskSources:
    def __init__(self) -> None:
        self.sources = {"jira-issue": _FakeTaskSource()}
        self.code_hosts: dict[str, object] = {}


class _FakeQuarantine:
    async def intake_for_new_task(self, intake):
        return IntakeOutcome(released=True, safe_content=intake.body)


class _FakeBoard:
    """Records accepted intakes and rejects a repeated (source, task_ref) —
    the same durable de-dup guarantee ``BoardStore.create_workflow``
    itself provides, standing in for it here."""

    def __init__(self) -> None:
        self.calls = []
        self.workflows: list[Workflow] = []
        self._seen: set[tuple[str, str]] = set()

    def create_workflow_from_intake(
        self, intake: AcceptedTaskIntake
    ) -> Workflow:
        key = (intake.source, intake.task_ref)
        if key in self._seen:
            raise WorkflowAlreadyExistsError(f"{key[0]}:{key[1]}")
        self._seen.add(key)
        self.calls.append(intake)
        workflow = Workflow(
            id=f"wf-{len(self.calls) - 1}",
            source=intake.source,
            task_ref=intake.task_ref,
            repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility,
            title=intake.title,
        )
        self.workflows.append(workflow)
        return workflow

    def list_workflows(self) -> list[Workflow]:
        return self.workflows


def _poll(jira, dismissals, board=None) -> JiraPollService:
    board = board or _FakeBoard()
    ingestion = IngestionService(
        Settings(_env_file=None),
        _FakeTaskSources(),
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
    dis = _FakeDismissals()
    board = _FakeBoard()
    poll = _poll(jira, dis, board)
    await poll.run_cycle()
    await poll.run_cycle()  # second cycle observes the same RFC
    assert [c.task_ref for c in board.calls] == ["RFC-1"]


@pytest.mark.asyncio
async def test_restart_with_existing_run_starts_no_duplicate() -> None:
    """Ensure a pre-existing board workflow (survived restart) blocks a
    new one for the same ticket."""
    jira = _FakeJira([Task("RFC-1", "t", "b")], fields={"RFC-1": "team/svc"})
    dis = _FakeDismissals()
    board = _FakeBoard()
    # Simulate a workflow rehydrated from the DB after restart.
    board.create_workflow_from_intake(
        AcceptedTaskIntake(
            source="jira-issue",
            task_ref="RFC-1",
            repo="team/svc",
            base_branch="main",
            source_visibility="private",
            title="t",
        )
    )
    await _poll(jira, dis, board).run_cycle()
    assert len(board.workflows) == 1  # no duplicate
