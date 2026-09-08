"""End-to-end review-feedback resume + triage step-selection (feature 013,
US3): a `done` run with an open PR resumes the SAME branch, and the
triage turn picks the right re-entry step from the feedback's content.

Runs against the real 6-step pipeline (feature 012): describe(0) ->
refine(1) -> gap_analysis(2) -> design(3) -> code(4) -> verify(5). A
plain ticket always terminates at `gap_analysis` (`decomposed`) rather
than reaching `design`/`code`/`verify` — the only way to reach `done` at
all (the starting point every resume test needs) is a
`SUBTASK_SENTINEL`-tagged body, which fast-paths describe/refine/
gap_analysis as already-done and lands straight at `design` (mirrors how
feature 012's own driver tests reach `design`/`code`/`verify`).
"""
from __future__ import annotations

import pytest

from app.storage.registry import SessionRegistry
from tests.conftest import (
    _FakeFeedbackStore,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _refine_noquestions,
    _service,
    _settings,
    _subtask_body,
    _verdict,
    _wait,
)


def _triage(step: str, reason: str = "r", instruction: str = "do it") -> str:
    return (
        f'<TRIAGE>{{"step": "{step}", "reason": "{reason}", '
        f'"instruction": "{instruction}"}}</TRIAGE>'
    )


async def _deliver_a_run(gh, runner, git, tmp_path):
    """Drive a run through design/code/verify to `done` + an open PR —
    the common starting point every resume test builds on. Uses the
    SUBTASK_SENTINEL fast path (feature 012) so describe/refine/
    gap_analysis are pre-marked done and the run lands straight at
    design, since a plain ticket would otherwise terminate at
    `gap_analysis` (`decomposed`) and never reach `done` at all."""
    gh.body = _subtask_body("Build a widget")
    svc = _service(
        gh, runner, git,
        settings=_settings(workspace_root=str(tmp_path)),
        feedback_store=_FakeFeedbackStore(),
    )
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "done")
    return svc, wid


@pytest.mark.asyncio
async def test_resume_uses_add_worktree_existing_not_add_worktree(
    tmp_path,
) -> None:
    """Ensure a `done` run with an open PR resumes onto its SAME branch
    (add_worktree_existing), not a fresh one (add_worktree)."""
    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nplan\n</PLAN>",
        "diff --git a/x b/x",
        _verdict(accept=True),
    ])
    svc, wid = await _deliver_a_run(gh, runner, git, tmp_path)

    seen: dict[str, list] = {"existing": []}
    orig_existing = git.add_worktree_existing

    async def _tracked_existing(mirror_dir, dest, branch):
        seen["existing"].append(branch)
        return await orig_existing(mirror_dir, dest, branch)

    git.add_worktree_existing = _tracked_existing
    runner._outputs.append(_triage("code"))
    runner._outputs.append("fixed diff")
    runner._outputs.append(_verdict(accept=True))

    run = svc.get(wid)
    branch_before = run.branch
    svc.resume_with_feedback(wid, "please fix a bug")
    await _wait(lambda: svc.get(wid).status == "done" and seen["existing"])

    assert seen["existing"] == [branch_before]


@pytest.mark.asyncio
async def test_resume_deliver_pushes_without_second_open_pr_and_one_comment(
    tmp_path,
) -> None:
    """Ensure deliver()'s second pass (via resume) pushes without a
    second open_change_request call, and posts exactly one landing
    comment for this round."""
    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nplan\n</PLAN>",
        "diff --git a/x b/x",
        _verdict(accept=True),
    ])
    svc, wid = await _deliver_a_run(gh, runner, git, tmp_path)
    first_pr_url = svc.get(wid).pr_url
    open_calls: list[str] = []
    orig_create = gh.create_pull_request

    async def _tracked_create(*args, **kwargs):
        open_calls.append("open")
        return await orig_create(*args, **kwargs)

    gh.create_pull_request = _tracked_create
    comments: list[str] = []
    source = svc._task_source(svc.get(wid))
    orig_post = source.post_comment

    async def _tracked_post(ref, body):
        comments.append(body)
        return await orig_post(ref, body)

    source.post_comment = _tracked_post

    runner._outputs.append(_triage("code"))
    runner._outputs.append("fixed diff")
    runner._outputs.append(_verdict(accept=True))

    svc.resume_with_feedback(wid, "please fix a bug")
    await _wait(lambda: svc.get(wid).status == "done" and comments)

    assert open_calls == []
    assert svc.get(wid).pr_url == first_pr_url
    assert comments == [f"Updated the change request: {first_pr_url}"]


@pytest.mark.asyncio
async def test_triage_selects_code_for_an_implementation_only_comment(
    tmp_path,
) -> None:
    """Ensure a feedback item that just names a bug routes to `code`."""
    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nplan\n</PLAN>",
        "diff --git a/x b/x",
        _verdict(accept=True),
    ])
    svc, wid = await _deliver_a_run(gh, runner, git, tmp_path)
    calls_before = len(runner.calls)
    runner._outputs.append(_triage("code", instruction="fix off-by-one"))
    runner._outputs.append("fixed diff")
    runner._outputs.append(_verdict(accept=True))

    svc.resume_with_feedback(wid, "there's an off-by-one bug in the loop")
    # Wait for the resume's own new turns (triage + code + verify), not
    # just status=="done" — that already held (stale) the instant this
    # call returns, before the spawned task's first `await`.
    await _wait(lambda: len(runner.calls) >= calls_before + 3)
    await _wait(lambda: svc.get(wid).status == "done")

    run = svc.get(wid)
    assert run.steps[4].status == "done"  # code step re-ran
    assert run.steps[1].status == "done"  # refine untouched
    assert run.steps[3].status == "done"  # design untouched


@pytest.mark.asyncio
async def test_triage_selects_design_and_it_reruns_gatelessly(
    tmp_path,
) -> None:
    """Ensure an approach-questioning comment routes to `design`, and
    since design has no gate on this branch, the run reaches `done`
    again without parking."""
    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nplan\n</PLAN>",
        "diff --git a/x b/x",
        _verdict(accept=True),
    ])
    svc, wid = await _deliver_a_run(gh, runner, git, tmp_path)
    runner._outputs.append(
        _triage("design", instruction="reconsider the data model")
    )
    runner._outputs.append("<PLAN>\nnew plan\n</PLAN>")
    runner._outputs.append("re-implemented diff")
    runner._outputs.append(_verdict(accept=True))

    svc.resume_with_feedback(wid, "why did you choose this architecture?")
    # Wait on the post-resume deliverable itself, not just status=="done"
    # — that status already held (stale, from the prior delivery) the
    # instant this call returns, before the spawned task's first `await`.
    await _wait(lambda: svc.get(wid).steps[3].deliverable == "new plan")
    await _wait(lambda: svc.get(wid).status == "done")

    run = svc.get(wid)
    assert run.steps[3].deliverable == "new plan"
    assert run.steps[1].status == "done"  # refine untouched


@pytest.mark.asyncio
async def test_triage_selects_refine_and_the_run_re_parks_at_the_gate(
    tmp_path,
) -> None:
    """Ensure a requirements-questioning comment routes to `refine`, and
    — since refine is a gated step — the run parks at the approval gate
    again rather than reaching `done` on its own."""
    gh, git = _FakeGitHub(body="vague issue"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nplan\n</PLAN>",
        "diff --git a/x b/x",
        _verdict(accept=True),
    ])
    svc, wid = await _deliver_a_run(gh, runner, git, tmp_path)
    runner._outputs.append(
        _triage("refine", instruction="should this even ingest CSV?")
    )
    runner._outputs.extend(_refine_noquestions("Build a widget, revised"))

    svc.resume_with_feedback(wid, "should we even support CSV uploads?")
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_approval"
    )

    run = svc.get(wid)
    assert run.steps[1].deliverable == "Build a widget, revised"
    assert run.status == "awaiting_refine_approval"
