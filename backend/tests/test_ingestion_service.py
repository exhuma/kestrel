"""Tests for the shared ingestion path (maybe_start_run).

Fixtures mirror ``tests/test_reconcile.py``'s board-domain doubles
(``_FakeTaskSources``/``_FakeBoard``/``BoardIntake``/``AcceptedTaskIntake``/
``Workflow``) — the shape ``IngestionService`` has taken since it was
rewritten off the deleted fixed-step driver (``app.services.workflows``,
``app.models_workflow.WorkflowRun``).
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import Workflow
from app.models_board_records import AcceptedTaskIntake, IntakeOutcome
from app.ports import Task
from app.services.board.quarantine import NewTaskIntake
from app.services.ingestion import BoardIntake, IngestionService


class _FakeTaskSource:
    """A task source returning a fixed, harmless body for canonical fetch."""

    def __init__(self, body: str = "b") -> None:
        self._body = body

    async def get_task(self, ref: str) -> Task:
        return Task(ref=ref, title="t", body=self._body)

    def visibility(self) -> str:
        return "public"


class _FakeTaskSources:
    """A minimal ``TaskSourceRegistry`` double."""

    def __init__(self, body: str = "b") -> None:
        self.sources = {"github-issue": _FakeTaskSource(body)}
        self.code_hosts: dict[str, object] = {}


class _FakeDismissals:
    """In-memory dismissal store keyed by task_ref."""

    def __init__(self) -> None:
        self._d: set[str] = set()

    def add(self, task_ref: str) -> None:
        self._d.add(task_ref)

    def is_dismissed(self, task_ref: str) -> bool:
        return task_ref in self._d

    def all(self) -> list[str]:
        return list(self._d)

    def clear(self, task_ref: str) -> None:
        self._d.discard(task_ref)


class _FakeQuarantine:
    """Always releases content unscreened; ingestion filters are what's
    under test here, not the quarantine boundary (see
    ``test_board_input_intake.py`` for that)."""

    async def intake_for_new_task(self, intake: NewTaskIntake) -> IntakeOutcome:
        return IntakeOutcome(released=True, safe_content=intake.body)


class _FakeBoard:
    """Records each accepted intake and returns a deterministic workflow."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[AcceptedTaskIntake] = []
        self.workflows: list[Workflow] = []
        self._fail = fail

    def create_workflow_from_intake(
        self, intake: AcceptedTaskIntake
    ) -> Workflow:
        if self._fail:
            raise RuntimeError("create failed")
        workflow = Workflow(
            id=f"wf-{len(self.calls)}",
            source=intake.source,
            task_ref=intake.task_ref,
            repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility,
            title=intake.title,
        )
        self.calls.append(intake)
        self.workflows.append(workflow)
        return workflow

    def list_workflows(self) -> list[Workflow]:
        return self.workflows


class _FakeGates:
    """Records each initial understanding-gate creation."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_gate(self, workflow_id: str, **_kwargs: object) -> None:
        self.calls.append(workflow_id)


def _board_intake(*, fail: bool = False) -> BoardIntake:
    return BoardIntake(_FakeQuarantine(), _FakeBoard(fail=fail), _FakeGates())


def _service(
    dismissals: _FakeDismissals,
    *,
    board_intake: BoardIntake | None = None,
    sources: _FakeTaskSources | None = None,
) -> IngestionService:
    source = TaskSourceConfig(type="github", watched_repos=["o/r"])
    settings = Settings(_env_file=None, task_sources=[source])
    return IngestionService(
        settings,
        sources or _FakeTaskSources(),
        dismissals,
        board_intake or _board_intake(),
    )


def _gh(task_ref: str, code_repo: str) -> dict:
    """GitHub-issue ingestion kwargs for maybe_start_run."""
    return dict(
        source="github-issue",
        task_ref=task_ref,
        code_repo=code_repo,
        issue_number=5,
    )


@pytest.mark.asyncio
async def test_starts_one_run_for_watched_repo() -> None:
    """Ensure a qualifying issue starts exactly one board workflow."""
    dis = _FakeDismissals()
    board_intake = _board_intake()
    rid = await _service(dis, board_intake=board_intake).maybe_start_run(
        **_gh("o/r#5", "o/r")
    )
    assert rid == "wf-0"
    assert [c.task_ref for c in board_intake.board.calls] == ["o/r#5"]


@pytest.mark.asyncio
async def test_ignores_unwatched_repo() -> None:
    """Ensure an unwatched repo starts nothing."""
    dis = _FakeDismissals()
    board_intake = _board_intake()
    got = await _service(dis, board_intake=board_intake).maybe_start_run(
        **_gh("x/y#5", "x/y")
    )
    assert got is None
    assert board_intake.board.calls == []


@pytest.mark.asyncio
async def test_ignores_dismissed_issue() -> None:
    """Ensure a dismissed (repo, issue) starts nothing."""
    dis = _FakeDismissals()
    dis.add("o/r#5")
    board_intake = _board_intake()
    got = await _service(dis, board_intake=board_intake).maybe_start_run(
        **_gh("o/r#5", "o/r")
    )
    assert got is None
    assert board_intake.board.calls == []


@pytest.mark.asyncio
async def test_never_starts_second_run_for_same_issue() -> None:
    """Ensure an existing board workflow for the ticket blocks a duplicate."""
    dis = _FakeDismissals()
    board_intake = _board_intake()
    svc = _service(dis, board_intake=board_intake)
    first = await svc.maybe_start_run(**_gh("o/r#5", "o/r"))
    second = await svc.maybe_start_run(**_gh("o/r#5", "o/r"))
    assert first == "wf-0"
    assert second is None
    assert len(board_intake.board.calls) == 1


@pytest.mark.asyncio
async def test_failed_create_leaves_no_run_or_dismissal() -> None:
    """Ensure a failed create leaves nothing for reconciliation to trip on."""
    dis = _FakeDismissals()
    board_intake = _board_intake(fail=True)
    with pytest.raises(RuntimeError):
        await _service(dis, board_intake=board_intake).maybe_start_run(
            **_gh("o/r#5", "o/r")
        )
    assert board_intake.board.workflows == []
    assert dis.is_dismissed("o/r#5") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker", ["<!-- kestrel:subtask -->", "<!-- kestrel:manual -->"]
)
async def test_a_former_child_ticket_is_an_ordinary_request(
    marker: str,
) -> None:
    """Ensure the retired child-ticket markers change nothing (feature 031,
    FR-017): a legacy child ticket starts a full request of its own."""
    board_intake = _board_intake()
    svc = _service(
        _FakeDismissals(),
        board_intake=board_intake,
        sources=_FakeTaskSources(body=f"Do it.\n\n{marker}\n"),
    )

    workflow_id = await svc.maybe_start_run(**_gh("o/r#2", "o/r"))

    assert workflow_id is not None
    assert board_intake.gates.calls == [workflow_id]
