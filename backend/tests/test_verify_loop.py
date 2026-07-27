"""Tests for the autonomous code<->verify loop (feature 003, US3)."""
# TODO(quality): refactor — exceeds the 500-line module guardrail. Split this
# module by concern rather than growing it further; grandfathered on
# 2026-07-27 (grew past the limit in earlier feature-005 verify-loop commits,
# uncaught until a release-tag CI run — see [quality-override] in that commit).
# pylint: disable=too-many-lines
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from app.config import Settings
from app.ports import Observation
from app.services.workflows import (
    CODE_PROMPT,
    EXPLORE_PROMPT,
    VERIFY_PROMPT,
    WorkflowService,
    _parse_verdict,
)
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.test_workflow_service import (
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refine_noquestions,
    _verdict,
    _wait,
)


def _svc(gh, runner, git, **opts) -> WorkflowService:
    """Build a test WorkflowService.

    ``opts`` (all optional): ``max_iter`` (default 3), ``workspace_root``,
    ``workflow_debug`` — folded into ``**opts`` rather than named keyword
    params to stay under the 5-argument limit.
    """
    settings_kwargs = {
        "git_base": "https://github.com", "github_token": "t",
        "max_verify_iterations": opts.get("max_iter", 3),
        "workflow_debug": opts.get("workflow_debug", False),
    }
    if opts.get("workspace_root") is not None:
        settings_kwargs["workspace_root"] = opts["workspace_root"]
    return WorkflowService(
        settings=Settings(**settings_kwargs),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git,
        github=gh,
        notifier=_FakeNotifier(),
    )


def test_parse_verdict() -> None:
    """Ensure the verdict parser reads accept/feedback and fails safe."""
    txt = '<VERDICT>{"accept": true, "feedback": ""}</VERDICT>'
    assert _parse_verdict(txt) == (True, "", [])
    txt = 'x <VERDICT>{"accept": false, "feedback": "no"}</VERDICT>'
    assert _parse_verdict(txt) == (False, "no", [])
    # Unparseable ⇒ reject (never ship unverified work).
    assert _parse_verdict("no verdict here")[0] is False


def test_parse_verdict_tolerates_common_formats() -> None:
    """Ensure the parser reads fenced or untagged JSON models often emit."""
    # JSON wrapped in a ``` fence inside the tags.
    fenced = (
        '<VERDICT>\n```json\n{"accept": true, "feedback": "ok"}\n```\n'
        "</VERDICT>"
    )
    assert _parse_verdict(fenced) == (True, "ok", [])
    # Tags dropped entirely, bare JSON in prose.
    bare = 'Here is my verdict: {"accept": false, "feedback": "nope"}'
    assert _parse_verdict(bare) == (False, "nope", [])
    # A fence with no explicit language tag.
    plain_fence = '```\n{"accept": true, "feedback": ""}\n```'
    assert _parse_verdict(plain_fence) == (True, "", [])


def test_parse_verdict_reads_observations() -> None:
    """Ensure a well-formed observations array parses into Observations."""
    txt = (
        '<VERDICT>{"accept": true, "feedback": "", "observations": '
        '[{"name": "GET /items", "kind": "http", "passed": true, '
        '"detail": "200 OK"}]}</VERDICT>'
    )
    accept, feedback, observations = _parse_verdict(txt)
    assert accept is True
    assert observations == [
        Observation(name="GET /items", kind="http", passed=True,
                    detail="200 OK")
    ]


def test_parse_verdict_no_observations_key_is_not_a_regression() -> None:
    """Ensure a verdict with no observations key parses exactly as before."""
    txt = '<VERDICT>{"accept": true, "feedback": "ok"}</VERDICT>'
    assert _parse_verdict(txt) == (True, "ok", [])


def test_parse_verdict_drops_malformed_observation_entries() -> None:
    """Ensure a malformed observation entry is dropped, not a parse failure."""
    txt = (
        '<VERDICT>{"accept": true, "feedback": "", "observations": '
        '[{"name": "ok one", "kind": "http", "passed": true}, '
        '{"kind": "http", "passed": true}, '
        '"not even an object", '
        '{"name": "bad kind", "kind": "sql", "passed": true}]}</VERDICT>'
    )
    accept, _, observations = _parse_verdict(txt)
    assert accept is True
    assert len(observations) == 1
    assert observations[0].name == "ok one"


@pytest.mark.asyncio
async def test_accept_first_round_opens_pr() -> None:
    """Ensure an accepted verdict opens the change request."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).pr_url == "https://github.com/o/r/pull/1"


@pytest.mark.asyncio
async def test_reject_then_accept_reruns_coder() -> None:
    """Ensure a rejected verdict re-runs the coder, then accepts."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",                       # design
        "coded v1", _verdict(accept=False, feedback="fix the edge case"),
        "coded v2", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    # Coder ran twice; the re-run carried the verifier's feedback.
    coder_prompts = [
        c["prompt"] for c in runner.calls
        if "implement" in c["prompt"].lower()
    ]
    assert any("fix the edge case" in p for p in coder_prompts)


@pytest.mark.asyncio
async def test_exhaustion_escalates_without_pr() -> None:
    """Ensure the loop escalates (no PR) when verification never passes."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    notifier = _FakeNotifier()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded", _verdict(accept=False, feedback="nope"),
        "coded", _verdict(accept=False, feedback="still nope"),
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t",
                          max_verify_iterations=2),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=git, github=gh, notifier=notifier,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert svc.get(wid).pr_url is None
    assert git.pushed == []
    assert "escalated" in notifier.notified


@pytest.mark.asyncio
async def test_no_awaiting_gate_during_autonomous_phases() -> None:
    """Ensure design/code/verify never enter an awaiting_* gate (FR-014)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    seen: list[str] = []

    class _RecordingNotifier(_FakeNotifier):
        def notify(self, run) -> None:
            seen.append(run.status)
            super().notify(run)

    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions, workflows=WorkflowRegistry(),
        backends=runner, git=git, github=gh, notifier=_RecordingNotifier(),
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    # The only awaiting_* status ever seen is the PRD gate.
    awaiting = [s for s in seen if s.startswith("awaiting_")]
    assert set(awaiting) <= {
        "awaiting_refine_approval", "awaiting_refine_input"
    }
    assert "designing" in seen and "coding" in seen and "verifying" in seen


@pytest.mark.asyncio
async def test_boundary_dispatches_explore_then_verdict_turn() -> None:
    """Ensure an http-boundary run runs a tool-enabled explore turn before
    the verdict turn, resuming the same session (feature 005, US1)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>\n<BOUNDARY>http</BOUNDARY>",  # design
        "coded",                                       # code
        "explored the running app",                     # verify: explore turn
        _verdict(accept=True),                          # verify: verdict turn
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    explore_call, verdict_call = runner.calls[-2], runner.calls[-1]
    assert explore_call["permission_mode"] != "plan"
    assert explore_call["resume_id"] is None
    assert verdict_call["permission_mode"] == "plan"
    explore_idx = len(runner.calls) - 2
    assert verdict_call["resume_id"] == f"s{explore_idx}"


@pytest.mark.asyncio
async def test_no_boundary_skips_explore_turn() -> None:
    """Ensure boundary=None/"none" runs today's single verdict-only turn —
    no explore turn is ever dispatched (feature 005, US1)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    outputs = [
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",  # no <BOUNDARY> tag -> boundary stays None
        "coded",
        _verdict(accept=True),  # verify: single turn, exactly as today
    ]
    runner = _FakeRunner(SessionRegistry(), outputs=list(outputs))
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    # One call per queued output (coordinator, writer, design, code,
    # verdict): if an explore turn had also been dispatched, the queue
    # above would have been exhausted early and the run would never reach
    # "done".
    assert len(runner.calls) == len(outputs)
    assert runner.calls[-1]["permission_mode"] == "plan"


@pytest.mark.asyncio
async def test_self_reported_observation_failure_forces_reject() -> None:
    """Ensure a failing self-reported observation rejects even though the
    verdict's own accept field says true — the http/ui analogue of
    test_failing_check_forces_reject (feature 005, US1)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>\n<BOUNDARY>ui</BOUNDARY>",
        "coded",
        "explored",  # verify: explore turn
        _verdict(
            accept=True,  # model says accept ...
            observations=[
                {"name": "login flow", "kind": "ui", "passed": False,
                 "detail": "spinner never resolved"},
            ],
        ),
    ])
    # max_iter=1 so exhaustion escalates after the single forced reject.
    svc = _svc(gh, runner, git, max_iter=1)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    # ... but the failing observation forces a reject -> exhaustion -> escalate.
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert svc.get(wid).pr_url is None


@pytest.mark.asyncio
async def test_quality_only_feedback_does_not_block_acceptance() -> None:
    """Ensure a code-quality concern in feedback does not block acceptance
    when nothing observed failed (feature 005, US2; FR-006/SC-005)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded",
        _verdict(
            accept=True,
            feedback="Works correctly, though the new function could use "
                     "a docstring and a shorter name.",
        ),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    # Accepted despite the quality concern in the verdict's own feedback
    # text — a full record of that feedback is a US3 concern (the
    # committed verify-report.md), not something the "accepted" deliverable
    # itself needs to carry.
    assert svc.get(wid).steps[3].deliverable == "accepted"


@pytest.mark.asyncio
async def test_failing_evidence_rejects_despite_positive_quality_feedback() -> (
    None
):
    """Ensure a failing self-reported observation still rejects even when
    the verdict's text is positive about code quality — the hard gate is
    never softened by advisory framing (feature 005, US2)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>\n<BOUNDARY>http</BOUNDARY>",
        "coded",
        "explored",  # verify: explore turn
        _verdict(
            accept=True,
            feedback="Code quality is excellent, clean, and well-documented.",
            observations=[
                {"name": "GET /items", "kind": "http", "passed": False,
                 "detail": "500 Internal Server Error"},
            ],
        ),
    ])
    svc = _svc(gh, runner, git, max_iter=1)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert svc.get(wid).pr_url is None


def test_explore_prompt_requires_stating_missing_tooling() -> None:
    """Ensure the explore-turn prompt instructs the agent to say so when
    boundary-appropriate tooling is unavailable, rather than silently
    degrading to diff-only judgment (FR-007)."""
    text = EXPLORE_PROMPT.lower()
    assert "not available" in text
    assert "explicitly" in text
    assert "boundary" in text


def test_code_prompt_requires_test_first_development() -> None:
    """Ensure the coder is explicitly told to practice TDD (FR-010): durable
    regression coverage is the coder's job, not verify's (feature 005)."""
    text = CODE_PROMPT.lower()
    assert "test-first" in text
    assert "testing pyramid" in text


def test_verify_prompts_do_not_reference_or_require_a_diff() -> None:
    """Ensure neither the explore nor the verdict prompt needs (or embeds)
    a diff — the coder and verifier share the worktree directly, so there
    is nothing to serialize (feature 006, Phase B)."""
    assert "{diff}" not in EXPLORE_PROMPT
    assert "{diff}" not in VERIFY_PROMPT
    # Both format cleanly without a diff kwarg.
    EXPLORE_PROMPT.format(boundary="http", prd="p", design="d")
    VERIFY_PROMPT.format(prd="p", design="d")


@pytest.mark.asyncio
async def test_coder_no_self_commit_triggers_safety_net_commit() -> None:
    """When the coder leaves its round uncommitted (the fake's default),
    kestrel's safety-net commits on its behalf (feature 006, Phase C)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded but forgot to commit", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert any(
        m.startswith("Auto-commit (round") for m in git.commit_messages
    )


@pytest.mark.asyncio
async def test_coder_self_commit_skips_safety_net_commit() -> None:
    """When the coder commits its own round, kestrel's safety-net
    auto-commit must not fire (feature 006, Phase C)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    git.rounds = [("diff --git a/x b/x", True)]  # coder self-commits
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded and committed", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert not any(
        m.startswith("Auto-commit (round") for m in git.commit_messages
    )


@pytest.mark.asyncio
async def test_no_changes_escalation_fires_on_self_committed_empty_diff() -> (
    None
):
    """Ensure the "no changes" escalation is based on the ref-aware round
    diff, not on whether the coder made a commit at all — a coder that
    "commits" an empty change must still escalate (feature 006, Phase C)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    git.rounds = [("", True)]  # coder "commits" but changes nothing
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "I looked but changed nothing",
    ])
    svc = _svc(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert svc.get(wid).error == "escalated: the coder produced no changes"


def _find_report(workspace: str) -> str:
    """Locate and read the committed verify-report.md under a worktree."""
    for root, _dirs, files in os.walk(os.path.join(workspace, ".kestrel")):
        if "verify-report.md" in files:
            return Path(root, "verify-report.md").read_text()
    raise AssertionError("verify-report.md not found under .kestrel/")


@pytest.mark.asyncio
async def test_verify_report_written_on_accept(tmp_path) -> None:
    """Ensure a committed verify-report.md exists once a run reaches
    "done", covering every round the loop ran (feature 005, US3)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded v1", _verdict(accept=False, feedback="fix the edge case"),
        "coded v2", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git, workspace_root=str(tmp_path))
    # A successful delivery tears the worktree down too (it's no longer
    # needed); neuter that here so the workspace survives to inspect.
    svc._teardown_workspace = lambda _run: asyncio.sleep(0)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    report = _find_report(svc.get(wid).workspace)
    assert "fix the edge case" in report  # round 1 (rejected)
    assert "accepted" in report.lower()  # round 2


@pytest.mark.asyncio
async def test_verify_report_written_on_escalate(tmp_path) -> None:
    """Ensure the report still exists (covering every attempted round) when
    the run escalates instead of completing (feature 005, US3)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded", _verdict(accept=False, feedback="nope"),
        "coded", _verdict(accept=False, feedback="still nope"),
    ])
    svc = _svc(gh, runner, git, max_iter=2, workspace_root=str(tmp_path))
    # Escalation tears the worktree down immediately, racing a test's read
    # of the report; neuter teardown here (a spy-style override, matching
    # this suite's existing pattern) so the workspace survives to inspect.
    svc._teardown_workspace = lambda _run: asyncio.sleep(0)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")
    workspace = svc.get(wid).workspace
    report = _find_report(workspace)
    assert "nope" in report
    assert "still nope" in report


@pytest.mark.asyncio
async def test_second_run_unaffected_by_first_runs_report(tmp_path) -> None:
    """Ensure a second, unrelated run's verify step is not influenced by a
    prior run's committed verify-report.md (feature 005, US3, FR-009)."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        # First run: rejects once, then accepts.
        *_refine_noquestions("prd one"),
        "<PLAN>d</PLAN>",
        "coded v1", _verdict(accept=False, feedback="fix X"),
        "coded v2", _verdict(accept=True),
        # Second run: accepts immediately — no code path reads the first
        # run's report as an obligation it must also satisfy.
        *_refine_noquestions("prd two"),
        "<PLAN>d2</PLAN>",
        "coded", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git, workspace_root=str(tmp_path))
    first = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(first).status == "awaiting_refine_approval")
    svc.approve(first)
    await _wait(lambda: svc.get(first).status == "done")

    second = await svc.create("o/r", 6)
    await _wait(lambda: svc.get(second).status == "awaiting_refine_approval")
    svc.approve(second)
    await _wait(lambda: svc.get(second).status == "done")
    assert svc.get(second).steps[3].deliverable == "accepted"


@pytest.mark.asyncio
async def test_workflow_debug_writes_dialogue_transcript(tmp_path) -> None:
    """Ensure workflow_debug appends the coder<->verifier exchange to a
    plain-text transcript next to (not inside) the worktree."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded v1", _verdict(accept=False, feedback="fix the edge case"),
        "coded v2", _verdict(accept=True),
    ])
    svc = _svc(
        gh, runner, git, workspace_root=str(tmp_path), workflow_debug=True
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    workspace = svc.get(wid).workspace
    transcript = Path(f"{workspace}-debug", "dialogue.log").read_text()
    assert "Round 1 — CODE PROMPT" in transcript
    assert "Round 1 — VERIFY PROMPT" in transcript
    assert "Round 1 — VERDICT" in transcript
    assert "accept=False" in transcript
    assert "fix the edge case" in transcript
    assert "Round 2 — CODE PROMPT" in transcript
    assert "accept=True" in transcript
    # The transcript lives beside the worktree, not inside it — it must
    # never be picked up by the worktree's own `git add -A`.
    assert not Path(workspace, "dialogue.log").exists()


@pytest.mark.asyncio
async def test_workflow_debug_off_writes_no_transcript(tmp_path) -> None:
    """Ensure the default (workflow_debug=False) creates no debug dir at all."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = _svc(gh, runner, git, workspace_root=str(tmp_path))
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    workspace = svc.get(wid).workspace
    assert not Path(f"{workspace}-debug").exists()


@pytest.mark.asyncio
async def test_workflow_debug_keeps_workspace_on_escalate(tmp_path) -> None:
    """Ensure workflow_debug skips auto-teardown so the worktree survives
    an escalation for inspection."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>",
        "coded", _verdict(accept=False, feedback="nope"),
    ])
    svc = _svc(
        gh, runner, git, max_iter=1, workspace_root=str(tmp_path),
        workflow_debug=True,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "escalated")
    assert Path(svc.get(wid).workspace).exists()


@pytest.mark.asyncio
async def test_workflow_debug_keeps_workspace_on_done(tmp_path) -> None:
    """Ensure workflow_debug also skips teardown after a successful run."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("prd"),
        "<PLAN>d</PLAN>", "coded", _verdict(accept=True),
    ])
    svc = _svc(
        gh, runner, git, workspace_root=str(tmp_path), workflow_debug=True
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert Path(svc.get(wid).workspace).exists()


@pytest.mark.asyncio
async def test_abandon_removes_workspace_despite_workflow_debug(
    tmp_path,
) -> None:
    """Ensure an explicit abandon still deletes the workspace even with
    workflow_debug on — only *automatic* cleanup is suppressed."""
    gh, git = _FakeGitHub(body="vague"), _FakeGit()
    runner = _FakeRunner(
        SessionRegistry(), outputs=[*_refine_noquestions("prd")]
    )
    svc = _svc(
        gh, runner, git, workspace_root=str(tmp_path), workflow_debug=True
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    workspace = svc.get(wid).workspace
    assert Path(workspace).exists()
    await svc.delete(wid)
    assert not Path(workspace).exists()
