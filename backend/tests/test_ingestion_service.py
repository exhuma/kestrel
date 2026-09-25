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
from app.persistence.child_task_store import ChildTaskSchedule
from app.ports import Task
from app.services.board.quarantine import NewTaskIntake
from app.services.ingestion import BoardIntake, IngestionService

_PARENT_AND_SUCCESSOR = 2


class _FakeTaskSource:
    """A task source returning a fixed, harmless body for canonical fetch."""

    async def get_task(self, ref: str) -> Task:
        return Task(ref=ref, title="t", body="b")

    def visibility(self) -> str:
        return "public"


class _FakeTaskSources:
    """A minimal ``TaskSourceRegistry`` double."""

    def __init__(self) -> None:
        self.sources = {"github-issue": _FakeTaskSource()}
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


class _FakeChildTasks:
    """In-memory child-link lifecycle double for re-adoption tests."""

    def __init__(self) -> None:
        """Create an empty linked-child state map."""
        self.states: dict[str, str] = {}
        self.latest: dict[str, str] = {}
        self.schedules: dict[str, ChildTaskSchedule] = {}
        self.generations: dict[str, str] = {}

    def record_run(self, task_ref: str, workflow_id: str) -> None:
        """Record a normal first-run association when the task is linked."""
        if task_ref in self.states:
            self.latest[task_ref] = workflow_id

    def scheduling_details(self, task_ref: str) -> ChildTaskSchedule | None:
        """Return scheduling metadata configured for one linked child."""
        return self.schedules.get(task_ref)

    def observe_source_state(self, task_ref: str, state: str) -> None:
        """Set the observed lifecycle state for a linked child."""
        if task_ref in self.states:
            self.states[task_ref] = state

    def linked_refs(self, prefix: str) -> set[str]:
        """Return linked child refs that use the source's native prefix."""
        return {
            task_ref for task_ref in self.states if task_ref.startswith(prefix)
        }

    def observe_generation(self, task_ref: str, generation: str) -> bool:
        """Report whether a local task child changed its explicit generation."""
        previous = self.generations.get(task_ref)
        self.generations[task_ref] = generation
        if previous is not None and previous != generation:
            self.states[task_ref] = "closed"
            return True
        return False

    def claim_reopen(self, task_ref: str, workflow_id: str) -> bool:
        """Claim a closed child only when its newest run matches the parent."""
        if self.states.get(task_ref) != "closed":
            return False
        if self.latest.get(task_ref) != workflow_id:
            return False
        self.states[task_ref] = "reopening"
        return True

    def complete_reopen(self, task_ref: str, workflow_id: str) -> None:
        """Store a successful successor as the child run head."""
        self.states[task_ref] = "open"
        self.latest[task_ref] = workflow_id

    def release_reopen(self, task_ref: str) -> None:
        """Release an unsuccessful claim for a later retry."""
        self.states[task_ref] = "closed"


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


def _board_intake(*, fail: bool = False) -> BoardIntake:
    return BoardIntake(_FakeQuarantine(), _FakeBoard(fail=fail))


def _service(
    dismissals: _FakeDismissals,
    *,
    board_intake: BoardIntake | None = None,
    children: _FakeChildTasks | None = None,
) -> IngestionService:
    source = TaskSourceConfig(type="github", watched_repos=["o/r"])
    settings = Settings(_env_file=None, task_sources=[source])
    return IngestionService(
        settings,
        _FakeTaskSources(),
        dismissals,
        board_intake or _board_intake(),
        children,
    )


def _gh(task_ref: str, code_repo: str) -> dict:
    """GitHub-issue ingestion kwargs for maybe_start_run."""
    return dict(
        source="github-issue",
        task_ref=task_ref,
        code_repo=code_repo,
        issue_number=5,
    )


def _intake(task_ref: str, title: str) -> AcceptedTaskIntake:
    return AcceptedTaskIntake(
        source="github-issue",
        task_ref=task_ref,
        repo="o/r",
        base_branch="main",
        source_visibility="public",
        title=title,
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
async def test_scheduled_child_bases_on_its_integration_branch() -> None:
    """A linked child's base branch comes from its scheduling metadata.

    Older prerequisite-readiness and repo-modifier-availability gating
    (the old driver's ``_is_startable``) is deliberately not covered
    here: ``IngestionService._scheduled_child``'s docstring documents
    that it was dropped rather than carried over — the property it
    protected (at most one writer per repository) is now enforced by
    the board's own workspace lease, not by ingestion-time gating. Only
    the ``integration_branch`` metadata is still consulted.
    """
    dis, children = _FakeDismissals(), _FakeChildTasks()
    children.schedules["o/r#2"] = ChildTaskSchedule(
        "TASK-2", ("TASK-1",), "kestrel/issue-1"
    )
    board_intake = _board_intake()
    svc = _service(dis, board_intake=board_intake, children=children)

    rid = await svc.maybe_start_run(**_gh("o/r#2", "o/r"))

    assert rid == "wf-0"
    assert board_intake.board.calls[0].base_branch == "kestrel/issue-1"


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
async def test_reopened_child_starts_one_linked_successor() -> None:
    """A claimed closed-to-open child transition bypasses only has_run."""
    dis, children = _FakeDismissals(), _FakeChildTasks()
    board_intake = _board_intake()
    parent = board_intake.board.create_workflow_from_intake(
        _intake("o/r#5", "t")
    )
    children.states[parent.task_ref] = "closed"
    children.latest[parent.task_ref] = parent.id
    svc = _service(dis, board_intake=board_intake, children=children)

    successor_id = await svc.maybe_start_reopened_successor(parent=parent)
    assert successor_id is not None
    assert successor_id != parent.id
    assert await svc.maybe_start_reopened_successor(parent=parent) is None
    assert children.states[parent.task_ref] == "open"
    assert children.latest[parent.task_ref] == successor_id


@pytest.mark.asyncio
async def test_failed_reopened_successor_releases_the_claim() -> None:
    """A create failure leaves the child eligible for a later reopen retry."""
    dis, children = _FakeDismissals(), _FakeChildTasks()
    parent = Workflow(
        id="wf-parent",
        source="github-issue",
        task_ref="o/r#5",
        repo="o/r",
        base_branch="main",
        source_visibility="public",
        title="t",
    )
    children.states[parent.task_ref] = "closed"
    children.latest[parent.task_ref] = parent.id
    board_intake = _board_intake(fail=True)
    svc = _service(dis, board_intake=board_intake, children=children)

    with pytest.raises(RuntimeError):
        await svc.maybe_start_reopened_successor(parent=parent)
    assert children.states[parent.task_ref] == "closed"


@pytest.mark.asyncio
async def test_missing_qualifying_child_is_closed_then_re_adopted() -> None:
    """A poll source's exit and re-entry creates one linked successor."""
    dis, children = _FakeDismissals(), _FakeChildTasks()
    board_intake = _board_intake()
    parent = board_intake.board.create_workflow_from_intake(
        _intake("RFC-5", "t")
    )
    children.states[parent.task_ref] = "open"
    children.latest[parent.task_ref] = parent.id
    svc = _service(dis, board_intake=board_intake, children=children)

    await svc.observe_missing_child_source_tasks("RFC-", set())
    await svc.observe_child_source_state(parent.task_ref, "open")
    await svc.observe_child_source_state(parent.task_ref, "open")

    successor_ids = [w.id for w in board_intake.board.workflows]
    assert len(successor_ids) == _PARENT_AND_SUCCESSOR
    assert children.latest[parent.task_ref] == successor_ids[-1]


@pytest.mark.asyncio
async def test_changed_local_task_generation_re_adopts_a_linked_child() -> None:
    """A local task generation changes only after its initial baseline."""
    dis, children = _FakeDismissals(), _FakeChildTasks()
    board_intake = _board_intake()
    parent = board_intake.board.create_workflow_from_intake(
        _intake("local:child", "t")
    )
    children.states[parent.task_ref] = "open"
    children.latest[parent.task_ref] = parent.id
    svc = _service(dis, board_intake=board_intake, children=children)

    await svc.observe_child_retrigger(parent.task_ref, "1")
    await svc.observe_child_retrigger(parent.task_ref, "1")
    await svc.observe_child_retrigger(parent.task_ref, "2")

    successor_ids = [w.id for w in board_intake.board.workflows]
    assert len(successor_ids) == _PARENT_AND_SUCCESSOR
    assert children.latest[parent.task_ref] == successor_ids[-1]
