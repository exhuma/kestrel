"""Tests for deliver()'s pr_number tracking + idempotency (feature 013, US3).

Split from ``test_workflow_service.py`` to keep that module under the
repo's module-length ceiling.
"""
from __future__ import annotations

import pytest

from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.storage.registry import SessionRegistry
from tests.conftest import _FakeGit, _FakeGitHub, _FakeRunner, _service

_OPENED_PR_NUMBER = 1
_RESUMED_PR_NUMBER = 9


def _delivery_run(workspace: str, **overrides) -> WorkflowRun:
    """A minimal, already-verified run ready for ``_deliver`` directly."""
    defaults = dict(
        id="wf-deliver", repo="o/r", issue_number=5,
        issue_title="Add widget", task_ref="o/r#5",
        base_branch="main", branch="kestrel/issue-5",
        workspace=workspace,
        steps=[WorkflowStep(name=s) for s in Step.sequence()],
    )
    defaults.update(overrides)
    return WorkflowRun(**defaults)


@pytest.mark.asyncio
async def test_deliver_sets_pr_number_from_the_opened_url(tmp_path) -> None:
    """Ensure a first deliver() pass parses pr_number out of pr_url —
    no migration data-fix needed for it."""
    gh, git = _FakeGitHub(body="x"), _FakeGit()
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), git)
    run = _delivery_run(str(tmp_path))
    svc.workflows.create(run)

    await svc._deliver(run)

    assert run.pr_url == "https://github.com/o/r/pull/1"
    assert run.pr_number == _OPENED_PR_NUMBER


@pytest.mark.asyncio
async def test_deliver_is_idempotent_for_an_already_open_pr(tmp_path) -> None:
    """Ensure a resumed run (pr_number already set) pushes without a
    second open_change_request call, and posts an "Updated" comment
    rather than a second "opened" one."""
    gh, git = _FakeGitHub(body="x"), _FakeGit()
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), git)
    run = _delivery_run(
        str(tmp_path),
        pr_url="https://github.com/o/r/pull/9", pr_number=_RESUMED_PR_NUMBER,
    )
    svc.workflows.create(run)
    open_calls: list[str] = []
    gh.create_pull_request = _track_calls(gh.create_pull_request, open_calls)
    comments: list[str] = []
    svc._task_source(run).post_comment = _record_comment(comments)

    await svc._deliver(run)

    assert open_calls == []
    assert run.pr_url == "https://github.com/o/r/pull/9"
    assert run.pr_number == _RESUMED_PR_NUMBER
    assert git.pushed == [run.branch]
    assert comments == [
        "Updated the change request: https://github.com/o/r/pull/9"
    ]


def _track_calls(original, calls: list[str]):
    async def _tracked(*args, **kwargs):
        calls.append("open_change_request")
        return await original(*args, **kwargs)

    return _tracked


def _record_comment(comments: list[str]):
    async def _post(_ref: str, body: str) -> str:
        comments.append(body)
        return ""

    return _post
