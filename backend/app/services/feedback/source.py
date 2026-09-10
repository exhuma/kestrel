"""Compositional feedback sources built from task and code-host ports."""

from __future__ import annotations

from typing import Protocol

from app.models_workflow import WorkflowRun
from app.ports import Acknowledgeable, Commentable, Feedback, FeedbackSource


class FeedbackTicketPort(Protocol):
    """The ticket operations required by a composed feedback source."""

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """List feedback-bearing comments on ``ref`` after ``since``."""
        ...

    async def acknowledge(self, feedback: Feedback) -> bool:
        """Best-effort acknowledgement of a ticket feedback item."""
        ...

    async def post_comment(self, ref: str, body: str) -> str:
        """Post a visible fallback reply on ``ref``."""
        ...


class FeedbackReviewPort(Protocol):
    """The review operations required by a composed feedback source."""

    async def list_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[Feedback]:
        """List feedback-bearing review comments after ``since``."""
        ...

    async def acknowledge(self, feedback: Feedback) -> bool:
        """Best-effort acknowledgement of a review feedback item."""
        ...


class FeedbackSourceFactory(Protocol):
    """Build a feedback source for a run from its current bound ports."""

    def __call__(
        self,
        run: WorkflowRun,
        task_source: FeedbackTicketPort,
        code_host: FeedbackReviewPort,
    ) -> FeedbackSource:
        """Return the feedback source composed for ``run``."""
        ...


class RunFeedbackSource:
    """Expose ticket and optional change-request feedback as one port."""

    def __init__(
        self,
        run: WorkflowRun,
        task_source: FeedbackTicketPort,
        code_host: FeedbackReviewPort,
    ) -> None:
        self._run = run
        self._task_source = task_source
        self._code_host = code_host

    async def list_feedback(
        self, run: WorkflowRun, cursor: str | None
    ) -> list[Feedback]:
        """Read ticket and, when present, review feedback for ``run``."""
        ref = run.task_ref or f"{run.repo}#{run.issue_number}"
        items = await self._task_source.list_comments(ref, since=cursor)
        if run.pr_number is not None and self._supports_change_requests():
            items.extend(
                await self._code_host.list_review_comments(
                    run.repo, run.pr_number, since=cursor
                )
            )
        return items

    def _supports_change_requests(self) -> bool:
        """Return review capability, defaulting legacy doubles to true."""
        capability = getattr(self._code_host, "supports_change_requests", None)
        return True if capability is None else capability()

    async def acknowledge(self, feedback: Feedback) -> bool:
        """Delegate acknowledgement to the port that produced ``feedback``."""
        if feedback.origin == "review":
            return await self._code_host.acknowledge(feedback)
        return await self._task_source.acknowledge(feedback)

    async def reply(self, feedback: Feedback, body: str) -> bool:
        """Post a fallback acknowledgement on this run's task source."""
        del feedback
        ref = self._run.task_ref or f"{self._run.repo}#{self._run.issue_number}"
        try:
            await self._task_source.post_comment(ref, body)
        except Exception:
            return False
        return True


class DirectFeedbackSource:
    """Adapt a direct webhook origin to the complete feedback-source port."""

    def __init__(self, source: Acknowledgeable, task_ref: str) -> None:
        self._source = source
        self._task_ref = task_ref

    async def list_feedback(
        self, run: WorkflowRun, cursor: str | None
    ) -> list[Feedback]:
        """Reject polling through an adapter intended only for webhooks."""
        del run, cursor
        raise NotImplementedError("direct feedback sources cannot poll")

    async def acknowledge(self, feedback: Feedback) -> bool:
        """Delegate acknowledgement to the direct origin."""
        return await self._source.acknowledge(feedback)

    async def reply(self, feedback: Feedback, body: str) -> bool:
        """Reply on the triggering ticket when the direct origin supports it."""
        del feedback
        if not isinstance(self._source, Commentable):
            return False
        try:
            await self._source.post_comment(self._task_ref, body)
        except Exception:
            return False
        return True


def feedback_source_for(
    source: Acknowledgeable | FeedbackSource, task_ref: str
) -> FeedbackSource:
    """Return ``source`` as a FeedbackSource, adapting direct webhook ports."""
    if isinstance(source, FeedbackSource):
        return source
    return DirectFeedbackSource(source, task_ref)


def compose_feedback_source(
    run: WorkflowRun,
    task_source: FeedbackTicketPort,
    code_host: FeedbackReviewPort,
) -> FeedbackSource:
    """Bind existing task and code-host adapters into one feedback source."""
    return RunFeedbackSource(run, task_source, code_host)
