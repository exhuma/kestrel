"""Tests for the shared ingestion path (maybe_start_run)."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import AcceptedTaskIntake, IntakeOutcome, Workflow
from app.models_workflow import WorkflowRun
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


class _FakeWorkflows:
    """Minimal WorkflowService stand-in: records creates, lists runs."""

    def __init__(self, fail: bool = False) -> None:
        self.runs: list[WorkflowRun] = []
        self.created: list[tuple[str, int | None, str]] = []
        self.base_branches: list[str | None] = []
        self.sources = {"github-issue": _FakeTaskSource()}
        self._fail = fail

    def list(self) -> list[WorkflowRun]:
        return self.runs

    async def create(
        self,
        repo: str,
        issue_number: int | None = None,
        *,
        source: str = "manual",
        task_ref: str | None = None,
        base_branch: str | None = None,
        **kwargs: object,
    ) -> str:
        if self._fail:
            raise RuntimeError("create failed")
        rid = f"wf-{len(self.created)}"
        self.created.append((repo, issue_number, source))
        self.base_branches.append(base_branch)
        parent_run_id = kwargs.get("parent_run_id")
        self.runs.append(
            WorkflowRun(
                id=rid,
                repo=repo,
                issue_number=issue_number,
                source=source,
                task_ref=task_ref or f"{repo}#{issue_number}",
                parent_run_id=(
                    parent_run_id if isinstance(parent_run_id, str) else None
                ),
            )
        )
        return rid


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

    def record_run(self, task_ref: str, workflow_id: str) -> None:
        """Record a normal first-run association when the task is linked."""
        if task_ref in self.states:
            self.latest[task_ref] = workflow_id

    def record(self, parent_workflow_id: str, task_ref: str) -> None:
        """Add a child link, matching the production persistence contract."""
        del parent_workflow_id
        self.states[task_ref] = "open"

    def scheduling_details(self, task_ref: str) -> ChildTaskSchedule | None:
        """Return scheduling metadata configured for one linked child."""
        return self.schedules.get(task_ref)

    def ready_task_node_ids(self, workflow_ids: set[str]) -> set[str]:
        """Map ready workflow IDs to their linked child node IDs."""
        return {
            schedule.task_node_id
            for task_ref, schedule in self.schedules.items()
            if self.latest.get(task_ref) in workflow_ids
        }

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
        previous = getattr(self, "generations", {}).get(task_ref)
        if not hasattr(self, "generations"):
            self.generations: dict[str, str] = {}
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
    """Records each accepted intake and returns a deterministic workflow id."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[AcceptedTaskIntake] = []
        self._fail = fail

    def create_workflow_from_intake(
        self, intake: AcceptedTaskIntake
    ) -> Workflow:
        if self._fail:
            raise RuntimeError("create failed")
        wf_id = f"wf-{len(self.calls)}"
        self.calls.append(intake)
        return Workflow(
            id=wf_id,
            source=intake.source,
            task_ref=intake.task_ref,
            repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility,
            title=intake.title,
        )


def _board_intake(*, fail: bool = False) -> BoardIntake:
    return BoardIntake(_FakeQuarantine(), _FakeBoard(fail=fail))


def _service(
    wf: _FakeWorkflows,
    dismissals: _FakeDismissals,
    *,
    board_intake: BoardIntake | None = None,
) -> IngestionService:
    source = TaskSourceConfig(type="github", watched_repos=["o/r"])
    settings = Settings(_env_file=None, task_sources=[source])
    return IngestionService(
        settings, wf, dismissals, board_intake or _board_intake()
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
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    board_intake = _board_intake()
    rid = await _service(wf, dis, board_intake=board_intake).maybe_start_run(
        **_gh("o/r#5", "o/r")
    )
    assert rid == "wf-0"
    assert [c.task_ref for c in board_intake.board.calls] == ["o/r#5"]


@pytest.mark.asyncio
async def test_ignores_unwatched_repo() -> None:
    """Ensure an unwatched repo starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    board_intake = _board_intake()
    got = await _service(
        wf, dis, board_intake=board_intake
    ).maybe_start_run(**_gh("x/y#5", "x/y"))
    assert got is None
    assert board_intake.board.calls == []


@pytest.mark.asyncio
async def test_ignores_dismissed_issue() -> None:
    """Ensure a dismissed (repo, issue) starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    dis.add("o/r#5")
    board_intake = _board_intake()
    got = await _service(
        wf, dis, board_intake=board_intake
    ).maybe_start_run(**_gh("o/r#5", "o/r"))
    assert got is None
    assert board_intake.board.calls == []


@pytest.mark.asyncio
async def test_never_starts_second_run_for_same_issue() -> None:
    """Ensure an existing run for the pair blocks a duplicate."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    board_intake = _board_intake()
    svc = _service(wf, dis, board_intake=board_intake)
    await svc.maybe_start_run(**_gh("o/r#5", "o/r"))
    wf.runs.append(WorkflowRun(id="wf-0", repo="o/r", task_ref="o/r#5"))
    assert await svc.maybe_start_run(**_gh("o/r#5", "o/r")) is None
    assert len(board_intake.board.calls) == 1


@pytest.mark.asyncio
async def test_child_waits_for_ready_prerequisites_and_availability() -> None:
    """DAG children start only after ready dependencies and no repo modifier."""
    wf, dis, children = _FakeWorkflows(), _FakeDismissals(), _FakeChildTasks()
    children.schedules["o/r#2"] = ChildTaskSchedule(
        "TASK-2", ("TASK-1",), "kestrel/issue-1"
    )
    board_intake = _board_intake()
    settings = _service(wf, dis).settings
    svc = IngestionService(settings, wf, dis, board_intake, children)

    assert await svc.maybe_start_run(**_gh("o/r#2", "o/r")) is None
    children.schedules["o/r#1"] = ChildTaskSchedule(
        "TASK-1", (), "kestrel/issue-1"
    )
    children.latest["o/r#1"] = "ready"
    wf.runs.append(
        WorkflowRun(id="ready", repo="o/r", status="technically_ready")
    )
    assert await svc.maybe_start_run(**_gh("o/r#2", "o/r")) == "wf-0"


@pytest.mark.asyncio
async def test_child_uses_parent_branch_and_waits_for_repo_modifier() -> None:
    """An eligible child bases on its parent branch, not a task-specific one."""
    wf, dis, children = _FakeWorkflows(), _FakeDismissals(), _FakeChildTasks()
    children.schedules["o/r#2"] = ChildTaskSchedule(
        "TASK-2", (), "kestrel/issue-1"
    )
    wf.runs.append(WorkflowRun(id="busy", repo="o/r", status="coding"))
    board_intake = _board_intake()
    settings = _service(wf, dis).settings
    svc = IngestionService(settings, wf, dis, board_intake, children)

    assert await svc.maybe_start_run(**_gh("o/r#2", "o/r")) is None
    wf.runs.clear()
    assert await svc.maybe_start_run(**_gh("o/r#2", "o/r")) == "wf-0"
    assert board_intake.board.calls[0].base_branch == "kestrel/issue-1"


@pytest.mark.asyncio
async def test_failed_create_leaves_no_run_or_dismissal() -> None:
    """Ensure a failed create leaves nothing for reconciliation to trip on."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    board_intake = _board_intake(fail=True)
    with pytest.raises(RuntimeError):
        await _service(
            wf, dis, board_intake=board_intake
        ).maybe_start_run(**_gh("o/r#5", "o/r"))
    assert wf.runs == []
    assert dis.is_dismissed("o/r#5") is False


@pytest.mark.asyncio
async def test_reopened_child_starts_one_linked_successor() -> None:
    """A claimed closed-to-open child transition bypasses only has_run."""
    wf, dis, children = _FakeWorkflows(), _FakeDismissals(), _FakeChildTasks()
    parent = WorkflowRun(
        id="wf-parent",
        repo="o/r",
        issue_number=5,
        source="github-issue",
        task_ref="o/r#5",
        base_branch="main",
    )
    wf.runs.append(parent)
    children.states[parent.task_ref] = "closed"
    children.latest[parent.task_ref] = parent.id
    settings = _service(wf, dis).settings
    svc = IngestionService(settings, wf, dis, _board_intake(), children)

    assert await svc.maybe_start_reopened_successor(parent=parent) == "wf-0"
    assert await svc.maybe_start_reopened_successor(parent=parent) is None
    assert wf.runs[-1].parent_run_id == parent.id
    assert children.states[parent.task_ref] == "open"


@pytest.mark.asyncio
async def test_failed_reopened_successor_releases_the_claim() -> None:
    """A create failure leaves the child eligible for a later reopen retry."""
    wf = _FakeWorkflows(fail=True)
    dis = _FakeDismissals()
    children = _FakeChildTasks()
    parent = WorkflowRun(id="wf-parent", repo="o/r", task_ref="o/r#5")
    children.states[parent.task_ref] = "closed"
    children.latest[parent.task_ref] = parent.id
    settings = _service(wf, dis).settings
    svc = IngestionService(settings, wf, dis, _board_intake(), children)

    with pytest.raises(RuntimeError):
        await svc.maybe_start_reopened_successor(parent=parent)
    assert children.states[parent.task_ref] == "closed"


@pytest.mark.asyncio
async def test_missing_qualifying_child_is_closed_then_re_adopted() -> None:
    """A poll source's exit and re-entry creates one linked successor."""
    wf, dis, children = _FakeWorkflows(), _FakeDismissals(), _FakeChildTasks()
    parent = WorkflowRun(id="wf-parent", repo="o/r", task_ref="RFC-5")
    wf.runs.append(parent)
    children.states[parent.task_ref] = "open"
    children.latest[parent.task_ref] = parent.id
    settings = _service(wf, dis).settings
    svc = IngestionService(settings, wf, dis, _board_intake(), children)

    await svc.observe_missing_child_source_tasks("RFC-", set())
    await svc.observe_child_source_state(parent.task_ref, "open")
    await svc.observe_child_source_state(parent.task_ref, "open")

    assert wf.runs[-1].parent_run_id == parent.id
    assert len(wf.runs) == _PARENT_AND_SUCCESSOR


@pytest.mark.asyncio
async def test_changed_local_task_generation_re_adopts_a_linked_child() -> None:
    """A local task generation changes only after its initial baseline."""
    wf, dis, children = _FakeWorkflows(), _FakeDismissals(), _FakeChildTasks()
    parent = WorkflowRun(id="wf-parent", repo="o/r", task_ref="local:child")
    wf.runs.append(parent)
    children.states[parent.task_ref] = "open"
    children.latest[parent.task_ref] = parent.id
    settings = _service(wf, dis).settings
    svc = IngestionService(settings, wf, dis, _board_intake(), children)

    await svc.observe_child_retrigger(parent.task_ref, "1")
    await svc.observe_child_retrigger(parent.task_ref, "1")
    await svc.observe_child_retrigger(parent.task_ref, "2")

    assert wf.runs[-1].parent_run_id == parent.id
    assert len(wf.runs) == _PARENT_AND_SUCCESSOR
