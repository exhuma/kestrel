"""Tests for the shared ingestion path (maybe_start_run)."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_workflow import WorkflowRun
from app.services.ingestion import IngestionService

_PARENT_AND_SUCCESSOR = 2


class _FakeWorkflows:
    """Minimal WorkflowService stand-in: records creates, lists runs."""

    def __init__(self, fail: bool = False) -> None:
        self.runs: list[WorkflowRun] = []
        self.created: list[tuple[str, int | None, str]] = []
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

    def record_run(self, task_ref: str, workflow_id: str) -> None:
        """Record a normal first-run association when the task is linked."""
        if task_ref in self.states:
            self.latest[task_ref] = workflow_id

    def record(self, parent_workflow_id: str, task_ref: str) -> None:
        """Add a child link, matching the production persistence contract."""
        del parent_workflow_id
        self.states[task_ref] = "open"

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
        """Report whether a fixture child changed its explicit generation."""
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


def _service(
    wf: _FakeWorkflows, dismissals: _FakeDismissals
) -> IngestionService:
    source = TaskSourceConfig(type="github", watched_repos=["o/r"])
    settings = Settings(_env_file=None, task_sources=[source])
    return IngestionService(settings, wf, dismissals)


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
    """Ensure a qualifying issue starts exactly one run tagged github-issue."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    rid = await _service(wf, dis).maybe_start_run(**_gh("o/r#5", "o/r"))
    assert rid == "wf-0"
    assert wf.created == [("o/r", 5, "github-issue")]


@pytest.mark.asyncio
async def test_ignores_unwatched_repo() -> None:
    """Ensure an unwatched repo starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    got = await _service(wf, dis).maybe_start_run(**_gh("x/y#5", "x/y"))
    assert got is None
    assert wf.created == []


@pytest.mark.asyncio
async def test_ignores_dismissed_issue() -> None:
    """Ensure a dismissed (repo, issue) starts nothing."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    dis.add("o/r#5")
    got = await _service(wf, dis).maybe_start_run(**_gh("o/r#5", "o/r"))
    assert got is None
    assert wf.created == []


@pytest.mark.asyncio
async def test_never_starts_second_run_for_same_issue() -> None:
    """Ensure an existing run for the pair blocks a duplicate."""
    wf, dis = _FakeWorkflows(), _FakeDismissals()
    svc = _service(wf, dis)
    await svc.maybe_start_run(**_gh("o/r#5", "o/r"))
    assert await svc.maybe_start_run(**_gh("o/r#5", "o/r")) is None
    assert len(wf.created) == 1


@pytest.mark.asyncio
async def test_failed_create_leaves_no_run_or_dismissal() -> None:
    """Ensure a failed create leaves nothing for reconciliation to trip on."""
    wf, dis = _FakeWorkflows(fail=True), _FakeDismissals()
    with pytest.raises(RuntimeError):
        await _service(wf, dis).maybe_start_run(**_gh("o/r#5", "o/r"))
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
    svc = IngestionService(_service(wf, dis).settings, wf, dis, children)

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
    svc = IngestionService(_service(wf, dis).settings, wf, dis, children)

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
    svc = IngestionService(_service(wf, dis).settings, wf, dis, children)

    await svc.observe_missing_child_source_tasks("RFC-", set())
    await svc.observe_child_source_state(parent.task_ref, "open")
    await svc.observe_child_source_state(parent.task_ref, "open")

    assert wf.runs[-1].parent_run_id == parent.id
    assert len(wf.runs) == _PARENT_AND_SUCCESSOR


@pytest.mark.asyncio
async def test_changed_fixture_generation_re_adopts_a_linked_child() -> None:
    """A fixture generation changes only after its initial baseline."""
    wf, dis, children = _FakeWorkflows(), _FakeDismissals(), _FakeChildTasks()
    parent = WorkflowRun(id="wf-parent", repo="o/r", task_ref="fixture:child")
    wf.runs.append(parent)
    children.states[parent.task_ref] = "open"
    children.latest[parent.task_ref] = parent.id
    svc = IngestionService(_service(wf, dis).settings, wf, dis, children)

    await svc.observe_child_retrigger(parent.task_ref, "1")
    await svc.observe_child_retrigger(parent.task_ref, "1")
    await svc.observe_child_retrigger(parent.task_ref, "2")

    assert wf.runs[-1].parent_run_id == parent.id
    assert len(wf.runs) == _PARENT_AND_SUCCESSOR
