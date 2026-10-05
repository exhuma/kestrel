"""Projection eligibility, idempotency, retry, and cleanup-ownership
tests for ``ProjectionsService`` (feature 026, T064/T065).

FR-033/FR-034 confine projections to four milestone kinds — ordinary
claims, retries, and routine completions never reach this ledger at all
(that filtering happens at the call site, not here); FR-035 makes the
ledger the durable boundary of what Kestrel may later clean up. Actually
posting to a task source is a later, old-driver-integration concern
(deferred to Phase 10) — this covers the idempotent ledger it will run on.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.board_projection_store import BoardProjectionStore
from app.services.board.projections import (
    ProjectionRequest,
    ProjectionsService,
    UnsupportedProjectionKindError,
)
from tests.board_test_support import board_session_factory
from tests.document_helpers import doc

_TASK_REF = "owner/repo#1"


def _service(tmp_path: Path) -> ProjectionsService:
    store = BoardProjectionStore(board_session_factory(tmp_path))
    return ProjectionsService(store)


def _plan(service: ProjectionsService, workflow_id, kind, key, text):
    return service.plan(
        ProjectionRequest(workflow_id, _TASK_REF, kind, key, doc(text))
    )


class TestPlanningEligibility:
    """Only the four FR-033 milestone kinds may be planned."""

    def test_plans_a_gate_projection(self, tmp_path: Path) -> None:
        service = _service(tmp_path)
        record = _plan(
            service, "wf-1", "gate", "wf-1:gate:understanding", "approved"
        )
        assert record.kind == "gate"
        assert record.state == "pending"

    @pytest.mark.parametrize(
        "kind",
        ["gate", "escalation", "approved_artifact", "delivery"],
    )
    def test_every_fr033_kind_is_accepted(
        self, tmp_path: Path, kind: str
    ) -> None:
        service = _service(tmp_path)
        record = _plan(service, "wf-1", kind, f"wf-1:{kind}:1", "x")
        assert record.kind == kind

    def test_child_work_is_no_longer_a_kind(self, tmp_path: Path) -> None:
        """Ensure no child-ticket write-back is ever planned (feature
        031, FR-021)."""
        service = _service(tmp_path)
        with pytest.raises(UnsupportedProjectionKindError):
            _plan(service, "wf-1", "child_work", "wf-1:child_work:1", "x")

    def test_unsupported_kind_is_rejected(self, tmp_path: Path) -> None:
        service = _service(tmp_path)
        with pytest.raises(UnsupportedProjectionKindError):
            _plan(service, "wf-1", "claim", "wf-1:claim:1", "x")

    def test_routine_completion_is_not_a_valid_kind(
        self, tmp_path: Path
    ) -> None:
        """FR-034: ordinary claims/retries/routine completions never
        project — "completion" is deliberately absent from the closed
        vocabulary a caller could even plan."""
        service = _service(tmp_path)
        with pytest.raises(UnsupportedProjectionKindError):
            _plan(service, "wf-1", "completion", "wf-1:completion:1", "x")


class TestIdempotency:
    """The same real-world event never plans a second projection."""

    def test_replanning_the_same_key_returns_the_original(
        self, tmp_path: Path
    ) -> None:
        service = _service(tmp_path)
        first = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "a")
        second = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "b")
        assert first.id == second.id

    def test_a_different_key_plans_independently(self, tmp_path: Path) -> None:
        service = _service(tmp_path)
        first = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "a")
        second = _plan(service, "wf-1", "gate", "wf-1:gate:prd", "b")
        assert first.id != second.id

    def test_webhook_and_poll_racing_the_same_milestone_project_once(
        self, tmp_path: Path
    ) -> None:
        """Simulates the Edge Cases scenario: a webhook and a poll cycle
        both observe the same milestone and both attempt to plan it."""
        service = _service(tmp_path)
        webhook_view = _plan(
            service, "wf-1", "delivery", "wf-1:delivery:pr-42", "merged"
        )
        poll_view = _plan(
            service, "wf-1", "delivery", "wf-1:delivery:pr-42", "merged"
        )
        assert webhook_view.id == poll_view.id


class TestRetry:
    """A failed projection stays visible for retry until it resolves."""

    def test_failed_projection_is_listed_as_retryable(
        self, tmp_path: Path
    ) -> None:
        service = _service(tmp_path)
        record = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "x")
        service.fail(record.id, "rate limited")

        retryable = service.retryable()

        assert [r.id for r in retryable] == [record.id]
        assert retryable[0].error == "rate limited"

    def test_completed_projection_is_not_retryable(
        self, tmp_path: Path
    ) -> None:
        service = _service(tmp_path)
        record = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "x")
        service.complete(record.id, external_id="comment-1")

        assert service.retryable() == []

    def test_a_retry_that_succeeds_clears_the_error(
        self, tmp_path: Path
    ) -> None:
        service = _service(tmp_path)
        record = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "x")
        service.fail(record.id, "rate limited")

        completed = service.complete(record.id, external_id="comment-1")

        assert completed.state == "completed"
        assert completed.error is None
        assert service.retryable() == []


class TestCleanupOwnership:
    """Only completed, externally-identified projections are cleanup-owned."""

    def test_completed_projection_is_owned(self, tmp_path: Path) -> None:
        service = _service(tmp_path)
        record = _plan(
            service, "wf-1", "approved_artifact",
            "wf-1:approved_artifact:g-1", "x",
        )
        service.complete(record.id, external_id="issue-99")

        owned = service.owned_external_ids("wf-1")

        assert owned == [("approved_artifact", "issue-99")]

    def test_pending_projection_is_not_yet_owned(self, tmp_path: Path) -> None:
        service = _service(tmp_path)
        _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "x")

        assert service.owned_external_ids("wf-1") == []

    def test_completed_without_an_external_id_is_not_owned(
        self, tmp_path: Path
    ) -> None:
        """A completed projection with no external_id created nothing
        externally (e.g. an internal-only milestone) — nothing to clean up."""
        service = _service(tmp_path)
        record = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "x")
        service.complete(record.id)

        assert service.owned_external_ids("wf-1") == []

    def test_ownership_is_scoped_to_its_own_workflow(
        self, tmp_path: Path
    ) -> None:
        service = _service(tmp_path)
        record = _plan(service, "wf-1", "gate", "wf-1:gate:understanding", "x")
        service.complete(record.id, external_id="comment-1")

        assert service.owned_external_ids("wf-2") == []
