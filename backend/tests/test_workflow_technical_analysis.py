"""Tests for the technical_analysis step: technical analysis and decomposition
into self-contained follow-up tasks (feature 012, spec.md User Story 3).

See specs/012-task-decomposition-pipeline/contracts/technical-analysis-output.md
for the contract these tests verify.
"""

from __future__ import annotations

import json

import pytest

from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _refine_noquestions,
    _service,
    _wait,
)


class _ChildTasks:
    """Records child links without requiring persistence in driver tests."""

    def __init__(self) -> None:
        """Create an empty recorded-link collection."""
        self.links: list[tuple[str, str]] = []
        self.metadata: list[tuple[str, tuple[str, ...], str]] = []

    def record(
        self, parent_workflow_id: str, task_ref: str, *_metadata: object
    ) -> None:
        """Record one parent-child source reference pair."""
        self.links.append((parent_workflow_id, task_ref))
        node_id, prerequisites, branch = _metadata
        prereq_values = (
            prerequisites if isinstance(prerequisites, tuple) else ()
        )
        self.metadata.append((str(node_id), prereq_values, str(branch)))


class _GHDouble(_FakeGitHub):
    """`_FakeGitHub` plus the two calls technical_analysis needs: creating a
    follow-up issue and commenting the technical-analysis summary back
    onto the original ticket. Kept local to this file rather than added
    to the shared conftest fake, to avoid touching it."""

    def __init__(self, body: str = "Please add a widget") -> None:
        super().__init__(body)
        self.created_issues: list[dict] = []
        self.comments: list[dict] = []
        self.fail_create_after = 0  # 0 = never fail
        self.empty_comment_after = 0  # 0 = never return an empty identifier

    async def create_issue(self, repo: str, title: str, body: str) -> int:
        if (
            self.fail_create_after
            and len(self.created_issues) >= self.fail_create_after
        ):
            raise RuntimeError("simulated create_issue failure")
        self.created_issues.append({"repo": repo, "title": title, "body": body})
        return 100 + len(self.created_issues)

    async def create_issue_comment(
        self, repo: str, number: int, body: str
    ) -> str:
        self.comments.append({"repo": repo, "number": number, "body": body})
        if (
            self.empty_comment_after
            and len(self.comments) >= self.empty_comment_after
        ):
            return ""
        return "https://c/1"


def _tech_analysis(text: str) -> str:
    return f"<TECH_ANALYSIS>{text}</TECH_ANALYSIS>"


def _followup_tasks(*tasks: dict) -> str:
    return f"<FOLLOWUP_TASKS>{json.dumps(list(tasks))}</FOLLOWUP_TASKS>"


def _containment(*verdicts: dict) -> str:
    payload = {"verdicts": list(verdicts)}
    return f"<CONTAINMENT>{json.dumps(payload)}</CONTAINMENT>"


def _technical_analysis_output(tech_text: str, *tasks: dict) -> str:
    """One technical_analysis analysis-turn response: decisions + candidates."""
    return _tech_analysis(tech_text) + "\n" + _followup_tasks(*tasks)


async def _reach_technical_analysis(gh: _FakeGitHub, extra_outputs: list[str]):
    """Drive a fresh run through describe + refine approval, then feed
    ``extra_outputs`` to technical_analysis. Returns (service, workflow_id)."""
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Add a widget.</UNDERSTANDING>",
            *_refine_noquestions("refined issue"),
            *extra_outputs,
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    return svc, wid


@pytest.mark.asyncio
async def test_parks_candidates_until_decomposition_is_approved() -> None:
    """Ensure analysis creates no task-source writes before approval."""
    gh = _GHDouble()
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Use a REST endpoint.",
                {"title": "Add the endpoint", "body": "Self-contained body"},
            ),
            _containment({"index": 0, "self_contained": True}),
        ],
    )

    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )

    run = svc.get(wid)
    assert run.steps[2].name == "technical_analysis"
    assert run.steps[2].status == "awaiting_approval"
    assert "Use a REST endpoint." in (run.steps[2].deliverable or "")
    assert len(gh.created_issues) == 0
    assert len(gh.comments) == 0

    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")

    assert run.steps[2].status == "done"
    assert len(gh.created_issues) == 1
    assert gh.created_issues[0]["title"] == "Add the endpoint"
    assert "kestrel:subtask" in gh.created_issues[0]["body"]
    assert isinstance(svc.git, _FakeGit)
    assert svc.git.pushed == [run.branch]
    # The summary is published to the *original* ticket via a distinct
    # comment call, not folded into the create_subtask calls (FR-012).
    expected_parent_comments = 2
    assert len(gh.comments) == expected_parent_comments
    assert "Use a REST endpoint." in gh.comments[0]["body"]
    assert gh.comments[0]["number"] == run.issue_number
    assert "CAB REVIEW REQUIRED" in gh.comments[1]["body"]
    assert "Recommendation:" not in gh.comments[1]["body"]
    assert "Estimated effort: 1 man-days" in gh.comments[1]["body"]
    assert "Coding-agent budget: 10000 tokens" in gh.comments[1]["body"]
    # The run never reaches design for the original ticket.
    assert run.steps[3].status == "pending"


@pytest.mark.asyncio
async def test_empty_cab_comment_confirmation_fails_the_run() -> None:
    """Ensure a missing CAB identifier prevents decomposition completion."""
    gh = _GHDouble()
    gh.empty_comment_after = 2
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Use a REST endpoint.",
                {"title": "Add the endpoint", "body": "Self-contained body"},
            ),
            _containment({"index": 0, "self_contained": True}),
        ],
    )
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "failed")
    assert "CAB decision summary publication" in (svc.get(wid).error or "")


@pytest.mark.asyncio
async def test_indivisible_work_still_yields_exactly_one_task() -> None:
    """Ensure a malformed/missing FOLLOWUP_TASKS block still publishes
    exactly one follow-up task (spec.md FR-009 — never zero)."""
    gh = _GHDouble()
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _tech_analysis("Nothing to split."),  # no FOLLOWUP_TASKS tag
            _containment({"index": 0, "self_contained": True}),
        ],
    )

    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert len(gh.created_issues) == 1
    assert "Delivery estimate" in gh.created_issues[0]["body"]
    assert "Recommended coding model: unknown" in gh.created_issues[0]["body"]


@pytest.mark.asyncio
async def test_publication_records_each_created_child_reference() -> None:
    """Approved publication persists each returned source task reference."""
    gh = _GHDouble()
    children = _ChildTasks()
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Two pieces.",
                {
                    "id": "TASK-1",
                    "title": "First",
                    "body": "First body",
                    "prerequisites": [],
                },
                {
                    "id": "TASK-2",
                    "title": "Second",
                    "body": "Second body",
                    "prerequisites": ["TASK-1"],
                },
            ),
            _containment(
                {"index": 0, "self_contained": True},
                {"index": 1, "self_contained": True},
            ),
        ],
    )
    svc.child_tasks = children

    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")

    assert children.links == [(wid, "o/r#101"), (wid, "o/r#102")]
    assert children.metadata == [
        ("TASK-1", (), "kestrel/issue-5"),
        ("TASK-2", ("TASK-1",), "kestrel/issue-5"),
    ]


@pytest.mark.asyncio
async def test_failing_self_containment_is_revised_before_publishing() -> None:
    """Ensure a task that fails the self-containment check is revised and
    re-checked before it is ever published — never on first failure."""
    gh = _GHDouble()
    revision = (
        '<FOLLOWUP_TASKS>[{"index": 0, "title": "Add the endpoint", '
        '"body": "Now inlines the shared schema decision"}]</FOLLOWUP_TASKS>'
    )
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Use a REST endpoint.",
                {"title": "Add the endpoint", "body": "references task 2"},
            ),
            _containment(
                {
                    "index": 0,
                    "self_contained": False,
                    "reason": "references task 2 without inlining it",
                }
            ),
            revision,
            _containment({"index": 0, "self_contained": True}),
        ],
    )

    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert len(gh.created_issues) == 1
    assert "inlines the shared schema decision" in gh.created_issues[0]["body"]
    assert "references task 2" not in gh.created_issues[0]["body"].replace(
        "Now inlines the shared schema decision", ""
    )


@pytest.mark.asyncio
async def test_create_subtask_failure_fails_the_run() -> None:
    """Ensure a create_subtask failure after the self-containment gate
    passed fails the run rather than publishing a partial set."""
    gh = _GHDouble()
    gh.fail_create_after = 1  # the second create_subtask call raises
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Two independent pieces.",
                {"title": "Piece one", "body": "Self-contained body one"},
                {"title": "Piece two", "body": "Self-contained body two"},
            ),
            _containment(
                {"index": 0, "self_contained": True},
                {"index": 1, "self_contained": True},
            ),
        ],
    )

    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "failed")
    assert svc.get(wid).status != "decomposed"


@pytest.mark.asyncio
async def test_request_changes_reruns_analysis_before_publishing() -> None:
    """Ensure requested changes replace candidates without stale publication."""
    gh = _GHDouble()
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "First analysis.", {"title": "First", "body": "First"}
            ),
            _containment({"index": 0, "self_contained": True}),
            (
                '<SCOPE>{"allowed": true, '
                '"reason": "Changes task granularity."}</SCOPE>'
            ),
            _technical_analysis_output(
                "Revised analysis.",
                {"title": "Revised", "body": "Revised body"},
            ),
            _containment({"index": 0, "self_contained": True}),
        ],
    )
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )

    svc.reject(wid, refinement_prompt="Use a smaller task")
    await _wait(
        lambda: "Revised analysis." in (svc.get(wid).steps[2].deliverable or "")
    )
    assert gh.created_issues == []
    assert len(gh.comments) == 1
    assert "Requested changes applied:" in gh.comments[0]["body"]
    assert "Canonical artifact:" in gh.comments[0]["body"]

    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert [issue["title"] for issue in gh.created_issues] == ["Revised"]


@pytest.mark.asyncio
async def test_out_of_scope_request_preserves_decomposition_candidate() -> None:
    """Ensure a PRD-conflicting amendment is refused without regeneration."""
    gh = _GHDouble()
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Analysis.", {"title": "Task", "body": "Body"}
            ),
            _containment({"index": 0, "self_contained": True}),
            (
                '<SCOPE>{"allowed": false, '
                '"reason": "Adds an unapproved outcome."}</SCOPE>'
            ),
        ],
    )
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )
    candidate = svc.get(wid).steps[2].deliverable

    svc.reject(wid, refinement_prompt="Also add an admin dashboard")
    await _wait(lambda: len(gh.comments) == 1)

    run = svc.get(wid)
    assert run.status == "awaiting_decomposition_approval"
    assert run.steps[2].deliverable == candidate
    assert "Adds an unapproved outcome." in gh.comments[-1]["body"]


@pytest.mark.asyncio
async def test_rejecting_decomposition_ends_the_run() -> None:
    """Ensure a bare rejection ends a parked decomposition run."""
    gh = _GHDouble()
    svc, wid = await _reach_technical_analysis(
        gh,
        [
            _technical_analysis_output(
                "Analysis.", {"title": "Task", "body": "Body"}
            ),
            _containment({"index": 0, "self_contained": True}),
        ],
    )
    await _wait(
        lambda: svc.get(wid).status == "awaiting_decomposition_approval"
    )

    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")
    assert gh.created_issues == []
    assert gh.comments == []
