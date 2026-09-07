"""Tests for the gap_analysis step: technical analysis and decomposition
into self-contained follow-up tasks (feature 012, spec.md User Story 3).

See specs/012-task-decomposition-pipeline/contracts/gap-analysis-output.md
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


class _GHDouble(_FakeGitHub):
    """`_FakeGitHub` plus the two calls gap_analysis needs: creating a
    follow-up issue and commenting the technical-analysis summary back
    onto the original ticket. Kept local to this file rather than added
    to the shared conftest fake, to avoid touching it."""

    def __init__(self, body: str = "Please add a widget") -> None:
        super().__init__(body)
        self.created_issues: list[dict] = []
        self.comments: list[dict] = []
        self.fail_create_after = 0  # 0 = never fail

    async def create_issue(self, repo: str, title: str, body: str) -> int:
        if (
            self.fail_create_after
            and len(self.created_issues) >= self.fail_create_after
        ):
            raise RuntimeError("simulated create_issue failure")
        self.created_issues.append(
            {"repo": repo, "title": title, "body": body}
        )
        return 100 + len(self.created_issues)

    async def create_issue_comment(
        self, repo: str, number: int, body: str
    ) -> str:
        self.comments.append({"repo": repo, "number": number, "body": body})
        return "https://c/1"


def _tech_analysis(text: str) -> str:
    return f"<TECH_ANALYSIS>{text}</TECH_ANALYSIS>"


def _followup_tasks(*tasks: dict) -> str:
    return f"<FOLLOWUP_TASKS>{json.dumps(list(tasks))}</FOLLOWUP_TASKS>"


def _containment(*verdicts: dict) -> str:
    payload = {"verdicts": list(verdicts)}
    return f"<CONTAINMENT>{json.dumps(payload)}</CONTAINMENT>"


def _gap_analysis_output(tech_text: str, *tasks: dict) -> str:
    """One gap_analysis analysis-turn response: decisions + candidates."""
    return _tech_analysis(tech_text) + "\n" + _followup_tasks(*tasks)


async def _reach_gap_analysis(gh: _FakeGitHub, extra_outputs: list[str]):
    """Drive a fresh run through describe + refine approval, then feed
    ``extra_outputs`` to gap_analysis. Returns (service, workflow_id)."""
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
async def test_decomposes_and_publishes_follow_up_tasks() -> None:
    """Ensure a successful gap_analysis publishes the follow-up task(s)
    and the technical-analysis summary, then ends the run decomposed."""
    gh = _GHDouble()
    svc, wid = await _reach_gap_analysis(
        gh,
        [
            _gap_analysis_output(
                "Use a REST endpoint.",
                {"title": "Add the endpoint", "body": "Self-contained body"},
            ),
            _containment({"index": 0, "self_contained": True}),
        ],
    )

    await _wait(lambda: svc.get(wid).status == "decomposed")

    run = svc.get(wid)
    assert run.steps[2].name == "gap_analysis"
    assert run.steps[2].status == "done"
    assert "Use a REST endpoint." in (run.steps[2].deliverable or "")
    assert len(gh.created_issues) == 1
    assert gh.created_issues[0]["title"] == "Add the endpoint"
    assert "kestrel:subtask" in gh.created_issues[0]["body"]
    # The summary is published to the *original* ticket via a distinct
    # comment call, not folded into the create_subtask calls (FR-012).
    assert len(gh.comments) == 1
    assert "Use a REST endpoint." in gh.comments[0]["body"]
    assert gh.comments[0]["number"] == run.issue_number
    # The run never reaches design for the original ticket.
    assert run.steps[3].status == "pending"


@pytest.mark.asyncio
async def test_indivisible_work_still_yields_exactly_one_task() -> None:
    """Ensure a malformed/missing FOLLOWUP_TASKS block still publishes
    exactly one follow-up task (spec.md FR-009 — never zero)."""
    gh = _GHDouble()
    svc, wid = await _reach_gap_analysis(
        gh,
        [
            _tech_analysis("Nothing to split."),  # no FOLLOWUP_TASKS tag
            _containment({"index": 0, "self_contained": True}),
        ],
    )

    await _wait(lambda: svc.get(wid).status == "decomposed")
    assert len(gh.created_issues) == 1


@pytest.mark.asyncio
async def test_failing_self_containment_is_revised_before_publishing() -> None:
    """Ensure a task that fails the self-containment check is revised and
    re-checked before it is ever published — never on first failure."""
    gh = _GHDouble()
    revision = (
        '<FOLLOWUP_TASKS>[{"index": 0, "title": "Add the endpoint", '
        '"body": "Now inlines the shared schema decision"}]</FOLLOWUP_TASKS>'
    )
    svc, wid = await _reach_gap_analysis(
        gh,
        [
            _gap_analysis_output(
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
    svc, wid = await _reach_gap_analysis(
        gh,
        [
            _gap_analysis_output(
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

    await _wait(lambda: svc.get(wid).status == "failed")
    assert svc.get(wid).status != "decomposed"
