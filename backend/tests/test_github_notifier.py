"""Tests for the GitHub-issue gate notifier and composite notifier."""
from __future__ import annotations

import asyncio

import pytest

from app.models_workflow import WorkflowRun
from app.notifications import (
    CompositeNotifier,
    GitHubIssueNotifier,
    gate_deep_link,
)

_GATES = [
    "awaiting_refine_input",
    "awaiting_refine_approval",
    "awaiting_plan_approval",
    "awaiting_implement_input",
    "awaiting_implement_approval",
]


class _FakeGitHub:
    def __init__(self, fail: bool = False) -> None:
        self.comments: list[tuple[str, int, str]] = []
        self._fail = fail

    async def create_issue_comment(self, repo, number, body):
        if self._fail:
            raise RuntimeError("boom")
        self.comments.append((repo, number, body))
        return "https://github.com/o/r/issues/5#c1"


class _Recording:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def notify(self, run: WorkflowRun) -> None:
        self.seen.append(run.id)


def _run(status: str) -> WorkflowRun:
    return WorkflowRun(id="wf-1", repo="o/r", issue_number=5, status=status)


async def _tick() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_deep_link_builder() -> None:
    """Ensure the deep-link builder respects the base URL."""
    assert gate_deep_link("https://k.example", "wf-1") == (
        "https://k.example/?run=wf-1"
    )
    assert gate_deep_link("https://k.example/", "wf-1") == (
        "https://k.example/?run=wf-1"
    )
    assert gate_deep_link("", "wf-1") == ""


@pytest.mark.asyncio
async def test_posts_comment_with_deep_link() -> None:
    """Ensure a gate posts a templated comment with the deep-link."""
    gh = _FakeGitHub()
    GitHubIssueNotifier(gh, "https://k.example").notify(
        _run("awaiting_refine_input")
    )
    await _tick()
    assert len(gh.comments) == 1
    repo, number, body = gh.comments[0]
    assert (repo, number) == ("o/r", 5)
    assert "Kestrel needs your input refining o/r#5." in body
    assert "Open in kestrel: https://k.example/?run=wf-1" in body


@pytest.mark.asyncio
async def test_posts_without_link_when_base_unset() -> None:
    """Ensure a link-less comment is posted when no base URL is set."""
    gh = _FakeGitHub()
    GitHubIssueNotifier(gh, "").notify(_run("awaiting_plan_approval"))
    await _tick()
    assert len(gh.comments) == 1
    assert "Open in kestrel" not in gh.comments[0][2]


@pytest.mark.asyncio
async def test_every_gate_posts_exactly_one_comment() -> None:
    """Ensure each awaiting_* status posts a single comment."""
    for status in _GATES:
        gh = _FakeGitHub()
        GitHubIssueNotifier(gh, "https://k.example").notify(_run(status))
        await _tick()
        assert len(gh.comments) == 1, status


@pytest.mark.asyncio
async def test_terminal_status_posts_nothing() -> None:
    """Ensure done/failed/rejected do not post a comment."""
    for status in ("done", "failed", "rejected", "planning"):
        gh = _FakeGitHub()
        GitHubIssueNotifier(gh, "https://k.example").notify(_run(status))
        await _tick()
        assert gh.comments == [], status


@pytest.mark.asyncio
async def test_post_failure_is_swallowed() -> None:
    """Ensure a failed GitHub post does not raise out of notify."""
    gh = _FakeGitHub(fail=True)
    # notify must return normally; the background task swallows + logs.
    GitHubIssueNotifier(gh, "https://k.example").notify(
        _run("awaiting_refine_input")
    )
    await _tick()
    assert gh.comments == []


@pytest.mark.asyncio
async def test_composite_records_inapp_even_when_github_fails() -> None:
    """Ensure the in-app notifier still runs when the GitHub notifier fails."""
    inapp = _Recording()
    gh = _FakeGitHub(fail=True)
    composite = CompositeNotifier(
        [inapp, GitHubIssueNotifier(gh, "https://k.example")]
    )
    composite.notify(_run("awaiting_refine_input"))
    await _tick()
    assert inapp.seen == ["wf-1"]
    assert gh.comments == []
