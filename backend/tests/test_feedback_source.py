"""Tests for compositional run feedback sources."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

import pytest

from app.models_workflow import WorkflowRun
from app.ports import Feedback
from app.services.feedback.source import compose_feedback_source


class _TaskSource:
    """Task-source double that records reads and replies."""

    def __init__(self) -> None:
        self.comments: list[tuple[str, str | None]] = []
        self.replies: list[tuple[str, str]] = []
        self.acknowledged: list[Feedback] = []

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """Record the ticket read and return one ticket item."""
        self.comments.append((ref, since))
        return [_feedback("ticket")]

    async def acknowledge(self, feedback: Feedback) -> bool:
        """Record a ticket acknowledgement."""
        self.acknowledged.append(feedback)
        return True

    async def post_comment(self, ref: str, body: str) -> str:
        """Record a fallback reply and return a placeholder URL."""
        self.replies.append((ref, body))
        return ""


class _CodeHost:
    """Code-host double that records review reads and acknowledgements."""

    def __init__(self) -> None:
        self.comments: list[tuple[str, int, str | None]] = []
        self.acknowledged: list[Feedback] = []

    async def list_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[Feedback]:
        """Record the review read and return one review item."""
        self.comments.append((repo, number, since))
        return [_feedback("review")]

    async def acknowledge(self, feedback: Feedback) -> bool:
        """Record a review acknowledgement."""
        self.acknowledged.append(feedback)
        return True


def _feedback(origin: Literal["ticket", "review"]) -> Feedback:
    """Build one feedback item for the requested origin."""
    return Feedback(
        external_id=origin,
        origin=origin,
        author="reviewer",
        body="@kestrel feedback",
        created_at=datetime(2026, 1, 1),
    )


def _run(pr_number: int | None = 7) -> WorkflowRun:
    """Build a run with a ticket and optionally an open change request."""
    return WorkflowRun(
        id="wf-1", repo="owner/repo", task_ref="owner/repo#1",
        pr_number=pr_number,
    )


@pytest.mark.asyncio
async def test_composed_source_reads_ticket_and_review_feedback() -> None:
    """The composed source delegates each run's reads to its existing ports."""
    task_source = _TaskSource()
    code_host = _CodeHost()
    run = _run()

    source = compose_feedback_source(run, task_source, code_host)

    assert await source.list_feedback(run, "ticket", "review") == [
        _feedback("ticket"), _feedback("review")
    ]
    assert task_source.comments == [("owner/repo#1", "ticket")]
    assert code_host.comments == [("owner/repo", 7, "review")]


@pytest.mark.asyncio
async def test_composed_source_routes_acknowledgement_and_reply() -> None:
    """Review acknowledgements use the host; fallbacks reply on the ticket."""
    task_source = _TaskSource()
    code_host = _CodeHost()
    source = compose_feedback_source(_run(), task_source, code_host)
    ticket = _feedback("ticket")
    review = _feedback("review")

    assert await source.acknowledge(ticket) is True
    assert await source.acknowledge(review) is True
    assert await source.reply(review, "Thanks") is True
    assert task_source.acknowledged == [ticket]
    assert code_host.acknowledged == [review]
    assert task_source.replies == [("owner/repo#1", "Thanks")]
