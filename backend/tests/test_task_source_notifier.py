"""Tests for the source-dispatching TaskSourceNotifier (feature 003)."""
from __future__ import annotations

import asyncio

import pytest

from app.models_workflow import WorkflowRun
from app.notifications import (
    CompositeNotifier,
    TaskSourceNotifier,
    gate_deep_link,
)


class _FakeSource:
    """A fake TaskSource recording the comments posted to it."""

    def __init__(self, fail: bool = False) -> None:
        self.comments: list[tuple[str, str]] = []
        self._fail = fail

    async def post_comment(self, task_ref: str, body: str) -> str:
        if self._fail:
            raise RuntimeError("boom")
        self.comments.append((task_ref, body))
        return "https://ticket/comment/1"


class _Recording:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def notify(self, run: WorkflowRun) -> None:
        self.seen.append(run.id)


def _run(status: str, *, source: str = "github-issue",
         task_ref: str = "o/r#5") -> WorkflowRun:
    return WorkflowRun(
        id="wf-1", repo="o/r", issue_number=5, status=status,
        source=source, task_ref=task_ref,
    )


async def _tick() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_deep_link_builder() -> None:
    """Ensure the deep-link builder respects the base URL."""
    assert gate_deep_link("https://k.example", "wf-1") == "https://k.example/?run=wf-1"
    assert gate_deep_link("https://k.example/", "wf-1") == "https://k.example/?run=wf-1"
    assert gate_deep_link("", "wf-1") == ""


@pytest.mark.asyncio
async def test_posts_thin_comment_with_deep_link() -> None:
    """Ensure a gate posts a templated comment with the deep-link."""
    gh = _FakeSource()
    TaskSourceNotifier({"github-issue": gh}, "https://k.example").notify(
        _run("awaiting_refine_input")
    )
    await _tick()
    assert len(gh.comments) == 1
    task_ref, body = gh.comments[0]
    assert task_ref == "o/r#5"
    assert "Kestrel needs your input refining o/r#5." in body
    assert "Open in kestrel: https://k.example/?run=wf-1" in body
    # Thin: no PRD/plan content, only status + link.
    assert "PRD" not in body or "PRD ready" in body


@pytest.mark.asyncio
async def test_dispatches_to_the_runs_own_source() -> None:
    """Ensure a Jira run's comment goes through the Jira source, not GitHub."""
    gh, jira = _FakeSource(), _FakeSource()
    notifier = TaskSourceNotifier(
        {"github-issue": gh, "jira-issue": jira}, "https://k.example"
    )
    notifier.notify(_run("awaiting_refine_approval", source="jira-issue",
                         task_ref="RFC-1"))
    await _tick()
    assert len(jira.comments) == 1 and jira.comments[0][0] == "RFC-1"
    assert gh.comments == []


@pytest.mark.asyncio
async def test_posts_without_link_when_base_unset() -> None:
    """Ensure a link-less comment is posted when no base URL is set."""
    gh = _FakeSource()
    TaskSourceNotifier({"github-issue": gh}, "").notify(
        _run("awaiting_refine_approval")
    )
    await _tick()
    assert len(gh.comments) == 1
    assert "Open in kestrel" not in gh.comments[0][1]


@pytest.mark.asyncio
async def test_gates_and_escalation_each_post_one_comment() -> None:
    """Ensure each awaiting_* gate and an escalation posts a single comment."""
    for status in ("awaiting_refine_input", "awaiting_refine_approval",
                   "escalated"):
        gh = _FakeSource()
        TaskSourceNotifier({"github-issue": gh}, "https://k.example").notify(
            _run(status)
        )
        await _tick()
        assert len(gh.comments) == 1, status


@pytest.mark.asyncio
async def test_non_attention_status_posts_nothing() -> None:
    """Ensure done/failed/rejected and transient phases post no comment."""
    for status in ("done", "failed", "rejected", "designing", "coding",
                   "verifying"):
        gh = _FakeSource()
        TaskSourceNotifier({"github-issue": gh}, "https://k.example").notify(
            _run(status)
        )
        await _tick()
        assert gh.comments == [], status


@pytest.mark.asyncio
async def test_unknown_source_or_no_task_ref_posts_nothing() -> None:
    """Ensure a run with no bound source (e.g. manual) posts nothing."""
    gh = _FakeSource()
    notifier = TaskSourceNotifier({"github-issue": gh}, "https://k.example")
    notifier.notify(_run("awaiting_refine_input", source="manual"))
    notifier.notify(_run("awaiting_refine_input", task_ref=""))
    await _tick()
    assert gh.comments == []


@pytest.mark.asyncio
async def test_post_failure_is_swallowed() -> None:
    """Ensure a failed post does not raise out of notify."""
    gh = _FakeSource(fail=True)
    TaskSourceNotifier({"github-issue": gh}, "https://k.example").notify(
        _run("awaiting_refine_input")
    )
    await _tick()
    assert gh.comments == []


@pytest.mark.asyncio
async def test_composite_records_inapp_even_when_source_fails() -> None:
    """Ensure the in-app notifier still runs when the source post fails."""
    inapp = _Recording()
    gh = _FakeSource(fail=True)
    composite = CompositeNotifier(
        [inapp, TaskSourceNotifier({"github-issue": gh}, "https://k.example")]
    )
    composite.notify(_run("awaiting_refine_input"))
    await _tick()
    assert inapp.seen == ["wf-1"]
    assert gh.comments == []
