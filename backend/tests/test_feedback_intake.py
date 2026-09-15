"""Tests for FeedbackIntakeService's pipeline (feature 013, US1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.models_workflow import WorkflowRun
from app.ports import Feedback
from app.services.feedback.intake import FeedbackIntakeService
from app.services.feedback.source import compose_feedback_source
from app.services.translation import Translator
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import _FakeFeedbackStore


class _FakeSource:
    """Records acknowledge calls; optionally raises to exercise the
    best-effort guard."""

    def __init__(
        self, raise_on_ack: bool = False, acknowledge_result: bool = True
    ) -> None:
        self.acknowledged: list[str] = []
        self.replies: list[tuple[Feedback, str]] = []
        self.posts: list[tuple[str, str]] = []
        self._raise = raise_on_ack
        self._acknowledge_result = acknowledge_result

    async def acknowledge(
        self, feedback: Feedback, token: str = "eyes"
    ) -> bool:
        del token
        if self._raise:
            raise RuntimeError("boom")
        self.acknowledged.append(feedback.external_id)
        return self._acknowledge_result

    async def reply(self, feedback: Feedback, body: str) -> bool:
        """Record a feedback-scoped reply without performing I/O."""
        self.replies.append((feedback, body))
        return True

    async def list_feedback(
        self,
        run: WorkflowRun,
        ticket_cursor: str | None,
        review_cursor: str | None,
    ) -> list[Feedback]:
        """Provide the complete source shape without polling test data."""
        del run, ticket_cursor, review_cursor
        return []

    async def list_comments(
        self, ref: str, since: str | None = None
    ) -> list[Feedback]:
        """Provide the ticket read shape needed by a composed source."""
        del ref, since
        return []

    async def list_review_comments(
        self, repo: str, number: int, since: str | None = None
    ) -> list[Feedback]:
        """Provide the review read shape needed by a composed source."""
        del repo, number, since
        return []

    async def post_comment(self, ref: str, body: str) -> str:
        """Record a visible ticket post made by a composed source."""
        self.posts.append((ref, body))
        return ""


class _FakeTranslator:
    """Returns a configured result or raises to exercise failure isolation."""

    def __init__(self, result: str | None = None) -> None:
        self._result = result

    async def translate(self, text: str) -> str:
        """Return ``text`` unchanged, a configured translation, or raise."""
        self.requested = text
        if self._result is None:
            raise RuntimeError("translation unavailable")
        return self._result


def _feedback(
    external_id="gh-issue-comment:o/r#1",
    body="@kestrel please fix this",
    author="octocat",
    origin="ticket",
) -> Feedback:
    return Feedback(
        external_id=external_id,
        origin=origin,
        author=author,
        body=body,
        created_at=datetime.now(timezone.utc),
    )


def _intake(
    settings=None,
    store=None,
    workflows=None,
    dispatch=None,
    translator: Translator | None = None,
) -> tuple[FeedbackIntakeService, list]:
    dispatched: list = []
    service = FeedbackIntakeService(
        settings or Settings(_env_file=None),
        store or _FakeFeedbackStore(),
        workflows or WorkflowRegistry(),
        dispatch or dispatched.append,
        translator,
    )
    return service, dispatched


@pytest.mark.asyncio
async def test_unmarked_feedback_is_never_persisted() -> None:
    """A comment without the marker is discarded before persistence."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(body="just a normal comment"),
        task_ref="o/r#1",
        source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_self_marked_approval_is_never_persisted_or_dispatched() -> None:
    """A personal-token Kestrel comment cannot approve its own gate."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(body="@kestrel approve\n\n[kestrel:posted]"),
        task_ref="o/r#1",
        source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_ignored_author_is_never_persisted() -> None:
    """An author on the denylist never produces a feedback_item row, even
    with the marker present."""
    store = _FakeFeedbackStore()
    settings = Settings(_env_file=None, feedback_ignore_authors=["kestrel-bot"])
    service, dispatched = _intake(settings=settings, store=store)

    await service.intake(
        _feedback(author="kestrel-bot"),
        task_ref="o/r#1",
        source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_kestrel_review_post_is_excluded_by_its_source_id() -> None:
    """Jira's human-looking service account needs no configured denylist."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(
            external_id="jira-comment:RFC-1:8",
            author="Kestrel Service",
            body=(
                "PRD ready for review: RFC-1.\n\n"
                "Revision 1: `[kestrel-review:current]`\n\n"
                "Reply to this review with its token and `@kestrel approve`, "
                "`@kestrel reject`, or `@kestrel request changes`."
            ),
        ),
        task_ref="RFC-1", source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_current_review_post_is_excluded_by_its_source_id() -> None:
    """The copyable-command review template must not self-trigger feedback."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(
            external_id="jira-comment:RFC-1:9",
            author="Kestrel Service",
            body=(
                "PRD ready for review: RFC-1.\n\n"
                "Revision 1: `[kestrel-review:current]`\n\n"
                "Reply with one command:\n"
                "- Approve with `@kestrel approve "
                "[kestrel-review:current]`\n"
                "- Reject with `@kestrel reject [kestrel-review:current]`\n"
                "- Request changes with `@kestrel request changes "
                "[kestrel-review:current]`."
            ),
        ),
        task_ref="RFC-1", source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_bot_flag_is_never_persisted() -> None:
    """A caller-flagged bot author is discarded even without a denylist
    entry (GitHub's user.type == "Bot" guard)."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(author="dependabot[bot]"),
        task_ref="o/r#1",
        source=_FakeSource(),
        is_bot=True,
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_stale_token_only_feedback_is_not_queued_mid_run() -> None:
    """A token for an old revision cannot enter a transient run's queue."""
    class _Reviews:
        """Report no supplied token as the active review revision."""

        def is_active(self, _token: str, _workflow_id: str, _gate: str) -> bool:
            """Reject the stale token used by this regression test."""
            return False

    workflows = WorkflowRegistry()
    workflows.create(WorkflowRun(id="wf-1", repo="o/r", task_ref="o/r#1"))
    store = _FakeFeedbackStore()
    workflows.review_requests = _Reviews()
    service, dispatched = _intake(store=store, workflows=workflows)

    await service.intake(
        _feedback(body="[kestrel-review:old] looks good"),
        task_ref="o/r#1", source=_FakeSource(),
    )

    assert store.items == {}
    assert dispatched == []


@pytest.mark.asyncio
async def test_marked_feedback_with_no_run_is_persisted_unrouted() -> None:
    """Ticket-origin feedback for a task_ref with no run yet is still
    persisted (workflow_id=None) — routing arrives if/when a run exists."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(
        _feedback(),
        task_ref="o/r#1",
        source=_FakeSource(),
    )

    item = store.items["gh-issue-comment:o/r#1"]
    assert item.workflow_id is None
    assert item.state == "queued"
    assert dispatched == [item]


@pytest.mark.asyncio
async def test_routes_to_the_newest_run_for_task_ref() -> None:
    """Ticket-origin feedback routes to the newest of several runs
    sharing the same task_ref."""
    workflows = WorkflowRegistry()
    workflows.create(WorkflowRun(id="wf-old", repo="o/r", task_ref="o/r#1"))
    workflows.create(WorkflowRun(id="wf-new", repo="o/r", task_ref="o/r#1"))
    store = _FakeFeedbackStore()
    service, _ = _intake(store=store, workflows=workflows)

    await service.intake(_feedback(), task_ref="o/r#1", source=_FakeSource())

    item = store.items["gh-issue-comment:o/r#1"]
    assert item.workflow_id == "wf-new"


@pytest.mark.asyncio
async def test_claim_dedups_a_race_between_transports() -> None:
    """A second intake call for the same external_id is a silent no-op —
    the dedup that guards a webhook/poll race or a re-delivery."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)

    await service.intake(_feedback(), task_ref="o/r#1", source=_FakeSource())
    await service.intake(_feedback(), task_ref="o/r#1", source=_FakeSource())

    assert len(store.items) == 1
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_queued_feedback_is_not_acknowledged() -> None:
    """Feedback retained for later processing produces no confirmation."""
    source = _FakeSource()
    service, _ = _intake()

    await service.intake(_feedback(), task_ref="o/r#1", source=source)

    assert source.acknowledged == []
    assert source.replies == []


@pytest.mark.asyncio
async def test_failed_acknowledge_never_blocks_immediate_action() -> None:
    """A failed confirmation leaves an immediate feedback action intact."""
    store = _FakeFeedbackStore()
    dispatched: list = []
    service, _ = _intake(
        store=store,
        dispatch=lambda item: (
            dispatched.append(item) or "The review is updated."
        ),
    )

    await service.intake(
        _feedback(),
        task_ref="o/r#1",
        source=_FakeSource(raise_on_ack=True),
    )

    assert len(store.items) == 1
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_immediate_action_replies_when_reaction_is_unavailable() -> None:
    """A failed reaction falls back to the specific completed action."""
    source = _FakeSource(acknowledge_result=False)
    service, _ = _intake(dispatch=lambda _item: "The review is being updated.")
    feedback = _feedback()

    await service.intake(feedback, task_ref="o/r#1", source=source)

    assert source.acknowledged == [feedback.external_id]
    assert source.replies == [(feedback, "The review is being updated.")]


@pytest.mark.asyncio
async def test_immediate_action_prefers_a_reaction_to_a_reply() -> None:
    """A source with reactions receives one low-noise confirmation signal."""
    source = _FakeSource()
    service, _ = _intake(dispatch=lambda _item: "The review is being updated.")

    await service.intake(_feedback(), task_ref="o/r#1", source=source)

    assert source.acknowledged == ["gh-issue-comment:o/r#1"]
    assert source.replies == []


@pytest.mark.asyncio
async def test_non_english_feedback_posts_disclaimer_translation() -> None:
    """Accepted non-English feedback is translated after workflow dispatch."""
    source = _FakeSource()
    service, dispatched = _intake(translator=_FakeTranslator("Please fix it."))
    feedback = _feedback(body="@kestrel arreglalo")

    await service.intake(feedback, task_ref="o/r#1", source=source)

    assert len(dispatched) == 1
    assert source.replies == [
        (
            feedback,
            "Automated English translation (may contain mistakes):\n\n"
            "> Please fix it.",
        )
    ]


@pytest.mark.asyncio
async def test_translation_failure_does_not_block_accepted_feedback() -> None:
    """A failed translation leaves accepted feedback dispatched and retained."""
    source = _FakeSource()
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store, translator=_FakeTranslator())

    await service.intake(
        _feedback(body="@kestrel arreglalo"), task_ref="o/r#1", source=source
    )

    assert len(store.items) == 1
    assert len(dispatched) == 1
    assert source.replies == []


@pytest.mark.asyncio
async def test_translation_reply_removes_the_configured_marker() -> None:
    """Translation quotes cannot reproduce the feedback trigger marker."""
    source = _FakeSource()
    service, _ = _intake(translator=_FakeTranslator("@kestrel Please fix it."))
    feedback = _feedback(body="@kestrel arreglalo")

    await service.intake(feedback, task_ref="o/r#1", source=source)

    assert source.replies[-1] == (
        feedback,
        "Automated English translation (may contain mistakes):\n\n"
        "> Please fix it.",
    )


@pytest.mark.asyncio
async def test_composed_poll_source_uses_reply_for_translation() -> None:
    """Poll-origin feedback translates through RunFeedbackSource.reply."""
    task_source = _FakeSource()
    run = WorkflowRun(id="wf-1", repo="o/r", task_ref="o/r#1")
    source = compose_feedback_source(run, task_source, _FakeSource())
    service, _ = _intake(translator=_FakeTranslator("Please fix it."))
    feedback = _feedback(body="@kestrel arreglalo")

    await service.intake(feedback, task_ref="o/r#1", source=source)

    assert task_source.posts == [
        (
            "o/r#1",
            "Automated English translation (may contain mistakes):\n\n"
            "> Please fix it.",
        ),
    ]


@pytest.mark.asyncio
async def test_tokenized_review_response_is_admitted_without_marker() -> None:
    """A reply can identify its revision instead of repeating the marker."""
    store = _FakeFeedbackStore()
    service, dispatched = _intake(store=store)
    feedback = _feedback(
        external_id="review-token",
        body="[kestrel-review:current] Looks good to me.",
    )

    await service.intake(feedback, task_ref="o/r#1", source=_FakeSource())

    assert dispatched[0].body == feedback.body
    assert "review-token" in store.items


@pytest.mark.asyncio
async def test_unclear_active_review_response_receives_clarification() -> None:
    """A current token with no decision is answered instead of ignored."""
    source = _FakeSource()
    service, _ = _intake(dispatch=lambda _item: "clarify")
    feedback = _feedback(body="[kestrel-review:current] What does this change?")

    await service.intake(feedback, task_ref="o/r#1", source=source)

    assert source.replies == [
        (feedback, "Please reply with approve, reject, or request changes.")
    ]
    assert source.acknowledged == []


@pytest.mark.asyncio
async def test_review_origin_is_not_routed_this_phase() -> None:
    """Review-origin feedback is persisted but not routed to a run this
    phase — that routing arrives with User Story 3's dispatch wiring."""
    workflows = WorkflowRegistry()
    workflows.create(WorkflowRun(id="wf-1", repo="o/r", task_ref="o/r#1"))
    store = _FakeFeedbackStore()
    service, _ = _intake(store=store, workflows=workflows)

    await service.intake(
        _feedback(origin="review"),
        task_ref="o/r#1",
        source=_FakeSource(),
    )

    item = store.items["gh-issue-comment:o/r#1"]
    assert item.workflow_id is None
