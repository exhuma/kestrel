"""Tests for the source-dispatching TaskSourceNotifier (feature 003)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.models_workflow import WorkflowRun, WorkflowStep
from app.notifications import (
    CompositeNotifier,
    TaskSourceNotifier,
    gate_deep_link,
)
from app.persistence.tables import ReviewRequestRow
from app.review_requests import render_delta_summary


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


class _ReviewRequests:
    """In-memory review-request ledger for notifier tests."""

    def __init__(self) -> None:
        self.rows: list[ReviewRequestRow] = []

    def active_for(
        self, workflow_id: str, gate: str
    ) -> ReviewRequestRow | None:
        """Return the active row for this workflow gate, if present."""
        return next(
            (
                row
                for row in self.rows
                if row.workflow_id == workflow_id
                and row.gate == gate
                and row.active
            ),
            None,
        )

    def token(self) -> str:
        """Return a predictable token for the next review request."""
        return f"token-{len(self.rows) + 1}"

    def next_revision(self, workflow_id: str) -> int:
        """Return a predictable revision for the next review request."""
        del workflow_id
        return len(self.rows) + 1

    def create(
        self, workflow_id: str, gate: str, revision: int, token: str
    ) -> ReviewRequestRow:
        """Create a predictable active revision for a workflow gate."""
        row = ReviewRequestRow(
            token=token,
            workflow_id=workflow_id,
            gate=gate,
            revision=revision,
            active=True,
            created_at=datetime.now(),
        )
        self.rows.append(row)
        return row


def _run(
    status: str, *, source: str = "github-issue", task_ref: str = "o/r#5"
) -> WorkflowRun:
    return WorkflowRun(
        id="wf-1",
        repo="o/r",
        issue_number=5,
        status=status,
        source=source,
        task_ref=task_ref,
    )


def _review_run(status: str) -> WorkflowRun:
    """Build a run containing each type of external-review artifact."""
    run = _run(status)
    run.steps = [
        WorkflowStep(name="describe"),
        WorkflowStep(name="refine"),
        WorkflowStep(name="gap_analysis"),
    ]
    run.steps[0].deliverable = "Understand the requested widget."
    run.steps[1].deliverable = "# PRD\n\nThe widget must be accessible."
    run.steps[2].deliverable = (
        '{"technical_analysis": "Use a REST endpoint.", "tasks": ['
        '{"title": "Add endpoint", "body": "Expose GET /widgets."}, '
        '{"title": "Add UI", "body": "Render the widget list."}]}'
    )
    return run


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
    assert "@kestrel" not in body
    assert "answer the questionnaire" in body
    assert "Open in kestrel: https://k.example/?run=wf-1" in body
    # Thin: no PRD/plan content, only status + link.
    assert "PRD" not in body or "PRD ready" in body


@pytest.mark.asyncio
async def test_gate_post_includes_a_durable_revision_token() -> None:
    """External gate posts state their revision and how to respond to it."""
    source, reviews = _FakeSource(), _ReviewRequests()
    TaskSourceNotifier({"github-issue": source}, "", reviews).notify(
        _run("awaiting_refine_approval")
    )
    await _tick()

    assert len(reviews.rows) == 1
    assert "Revision 1: `[kestrel-review:token-1]`" in source.comments[0][1]
    assert "Reply with one command:" in source.comments[0][1]
    commands = source.comments[0][1]
    assert "@kestrel approve [kestrel-review:token-1]" in commands
    assert "@kestrel reject [kestrel-review:token-1]" in commands
    assert "@kestrel request changes [kestrel-review:token-1]" in commands


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "artifact"),
    [
        ("awaiting_describe_approval", "Understand the requested widget."),
        ("awaiting_refine_approval", "The widget must be accessible."),
        ("awaiting_decomposition_approval", "Use a REST endpoint."),
    ],
)
async def test_external_review_post_contains_its_artifact_before_link(
    status: str, artifact: str
) -> None:
    """External reviews lead with a complete artifact, not the Kestrel UI."""
    source, reviews = _FakeSource(), _ReviewRequests()
    notifier = TaskSourceNotifier(
        {"github-issue": source}, "https://k.example", reviews
    )
    notifier.notify(_review_run(status))
    await _tick()

    body = source.comments[0][1]
    assert artifact in body
    assert body.index(artifact) < body.index("[kestrel-review:token-1]")
    assert body.index("[kestrel-review:token-1]") < body.index(
        "Open in kestrel"
    )


@pytest.mark.asyncio
async def test_decomposition_review_renders_numbered_candidate_tasks() -> None:
    """Persisted candidate JSON is readable in the external review post."""
    source, reviews = _FakeSource(), _ReviewRequests()
    TaskSourceNotifier({"github-issue": source}, "", reviews).notify(
        _review_run("awaiting_decomposition_approval")
    )
    await _tick()

    body = source.comments[0][1]
    assert "## Technical analysis" in body
    assert "## Proposed child tasks" in body
    assert "1. **Add endpoint**" in body
    assert "2. **Add UI**" in body


@pytest.mark.asyncio
async def test_external_review_without_ledger_still_posts_the_artifact() -> (
    None
):
    """A legacy notifier cannot turn an external review into a UI-only gate."""
    source = _FakeSource()
    TaskSourceNotifier({"github-issue": source}, "https://k.example").notify(
        _review_run("awaiting_refine_approval")
    )
    await _tick()

    body = source.comments[0][1]
    assert body.index("The widget must be accessible.") < body.index(
        "Open in kestrel"
    )


def test_delta_summary_references_canonical_artifact() -> None:
    """A revised review post is concise and sends readers to the source."""
    summary = render_delta_summary(
        "One\nOld value", "One\nNew value", "https://k.example/?run=wf-1"
    )

    assert "New value" in summary
    assert "Old value" not in summary
    assert "https://k.example/?run=wf-1" in summary
    assert "kestrel-review:" not in summary


@pytest.mark.asyncio
async def test_questionnaire_post_never_creates_a_review_request() -> None:
    """Refine interview input remains a UI-only questionnaire interaction."""
    source, reviews = _FakeSource(), _ReviewRequests()
    notifier = TaskSourceNotifier(
        {"github-issue": source}, "https://k.example", reviews
    )
    notifier.notify(_run("awaiting_refine_input"))
    await _tick()

    assert reviews.rows == []
    assert "kestrel-review:" not in source.comments[0][1]
    assert "@kestrel" not in source.comments[0][1]


@pytest.mark.asyncio
async def test_dispatches_to_the_runs_own_source() -> None:
    """Ensure a Jira run's comment goes through the Jira source, not GitHub."""
    gh, jira = _FakeSource(), _FakeSource()
    notifier = TaskSourceNotifier(
        {"github-issue": gh, "jira-issue": jira}, "https://k.example"
    )
    notifier.notify(
        _run("awaiting_refine_approval", source="jira-issue", task_ref="RFC-1")
    )
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
    for status in (
        "awaiting_refine_input",
        "awaiting_refine_approval",
        "escalated",
    ):
        gh = _FakeSource()
        TaskSourceNotifier({"github-issue": gh}, "https://k.example").notify(
            _run(status)
        )
        await _tick()
        assert len(gh.comments) == 1, status


@pytest.mark.asyncio
async def test_repeated_same_status_posts_once() -> None:
    """A re-save of the same gate status (an interview round, a
    reject-and-retry loop) must not repost an identical comment."""
    gh = _FakeSource()
    notifier = TaskSourceNotifier({"github-issue": gh}, "https://k.example")
    run = _run("awaiting_refine_input")
    notifier.notify(run)
    notifier.notify(run)
    notifier.notify(run)
    await _tick()
    assert len(gh.comments) == 1


@pytest.mark.asyncio
async def test_distinct_statuses_each_post() -> None:
    """A genuinely new gate status still posts its own comment."""
    gh = _FakeSource()
    notifier = TaskSourceNotifier({"github-issue": gh}, "https://k.example")
    notifier.notify(_run("awaiting_describe_approval"))
    notifier.notify(_run("awaiting_refine_approval"))
    await _tick()
    assert [ref for ref, _ in gh.comments] == ["o/r#5", "o/r#5"]


@pytest.mark.asyncio
async def test_same_status_reposts_after_leaving_the_gate() -> None:
    """Once a run leaves its gate, a later visit to the same status
    (a different episode) posts again rather than staying suppressed
    forever."""
    gh = _FakeSource()
    notifier = TaskSourceNotifier({"github-issue": gh}, "https://k.example")
    notifier.notify(_run("awaiting_refine_input"))
    notifier.notify(_run("refining"))  # gate cleared
    notifier.notify(_run("awaiting_refine_input"))  # a later, new episode
    await _tick()
    assert [ref for ref, _ in gh.comments] == ["o/r#5", "o/r#5"]


@pytest.mark.asyncio
async def test_non_attention_status_posts_nothing() -> None:
    """Ensure done/failed/rejected and transient phases post no comment."""
    for status in (
        "done",
        "failed",
        "rejected",
        "designing",
        "coding",
        "verifying",
    ):
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
async def test_failed_gate_post_is_retried_without_recording_a_token() -> None:
    """A failed post leaves no active token and does not suppress a retry."""
    source, reviews = _FakeSource(fail=True), _ReviewRequests()
    notifier = TaskSourceNotifier({"github-issue": source}, "", reviews)
    run = _run("awaiting_refine_approval")
    notifier.notify(run)
    await _tick()

    assert reviews.rows == []
    source._fail = False
    notifier.notify(run)
    await _tick()

    assert len(source.comments) == 1
    assert len(reviews.rows) == 1


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
