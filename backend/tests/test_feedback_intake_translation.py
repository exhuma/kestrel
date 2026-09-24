"""Tests for FeedbackIntakeService's translation-disclaimer behavior.

Split out of ``test_feedback_intake.py`` for module-length budget (feature
013, US1) — see that file for the shared ``_intake``/``_feedback``/
``_FakeSource`` fixtures reused here.
"""

from __future__ import annotations

import pytest

from app.models_workflow import WorkflowRun
from app.services.feedback.source import compose_feedback_source
from tests.conftest import _FakeFeedbackStore
from tests.test_feedback_intake import _FakeSource, _feedback, _intake


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
