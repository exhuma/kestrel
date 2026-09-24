"""The fail-closed untrusted-input boundary (feature 026, FR-018..FR-023).

Every external or human-gate input — a task body, feedback item, gate
edit, questionnaire answer, or direct session prompt — passes through
:class:`QuarantineService` before it can reach an agent, a workflow
transition, or a task-source write. Oversized content, a missing/
incapable input-security specialist, and any malformed or timed-out
classification all fail closed into quarantine (FR-020); nothing here
ever treats an unclear result as safe.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models_board import IntakeOutcome, SecurityReviewRecord, Workflow
from app.persistence.board_quarantine_store import (
    BoardQuarantineStore,
    QuarantineRequest,
)
from app.policy import SpecialistBackendPolicy, SpecialistCapabilityError
from app.services.board.dispatch import (
    ClassificationError,
    ClassificationResult,
    build_classification_envelope,
    classify_input,
)
from app.services.board.specialists import SpecialistRoster

#: Bumped when the deterministic screening/classification policy changes.
POLICY_VERSION = "v1"

_INPUT_SECURITY_ROLE = "input-security"


@dataclass(frozen=True)
class NewTaskIntake:
    """A newly ingested task's identity and body, before any workflow exists.

    :param source: Source origin (e.g. ``"github-issue"``).
    :param task_ref: Source-native task identity.
    :param body: The canonically fetched, untrusted task body.
    """

    source: str
    task_ref: str
    body: str


@dataclass(frozen=True)
class ExistingWorkflowIntake:
    """Untrusted content targeting an already-known piece of work.

    :param identity_ref: A stable identity for this content's target
        (e.g. a feedback item's external id) — used to build the dedup
        identity when no board workflow exists yet to host the review
        (feedback and gates still target the pre-board ``WorkflowRun``
        model during this feature's coexistence window).
    :param category: A safe label for the review card (e.g. ``"feedback"``,
        ``"gate answer"``).
    :param content: The untrusted content.
    :param workflow: The board workflow to attach a review card to, when
        one exists.
    """

    identity_ref: str
    category: str
    content: str
    workflow: Workflow | None = None


class QuarantineService:
    """Screens untrusted input and records/resolves quarantine decisions."""

    def __init__(
        self,
        quarantine_store: BoardQuarantineStore,
        roster: SpecialistRoster,
        backend_policy: SpecialistBackendPolicy,
        max_bytes: int,
        classify_timeout_seconds: float,
    ) -> None:
        self._store = quarantine_store
        self._roster = roster
        self._backend_policy = backend_policy
        self._max_bytes = max_bytes
        self._classify_timeout_seconds = classify_timeout_seconds

    async def intake_for_new_task(self, intake: NewTaskIntake) -> IntakeOutcome:
        """Screen a newly ingested task's body (FR-018)."""
        return await self._intake(
            workflow=None,
            source_identity=f"{intake.source}:{intake.task_ref}",
            content=intake.body,
            card_title=f"Security review: {intake.task_ref}",
        )

    async def intake_for_existing_workflow(
        self, intake: ExistingWorkflowIntake
    ) -> IntakeOutcome:
        """Screen content targeting existing work (feedback/gate input/
        direct prompt)."""
        identity_base = (
            intake.workflow.id if intake.workflow is not None
            else intake.identity_ref
        )
        return await self._intake(
            workflow=intake.workflow,
            source_identity=f"{identity_base}:{intake.category}",
            content=intake.content,
            card_title=f"Security review: {intake.category}",
        )

    async def _intake(
        self,
        *,
        workflow: Workflow | None,
        source_identity: str,
        content: str,
        card_title: str,
    ) -> IntakeOutcome:
        content_hash = hashlib.sha256(
            content.encode("utf-8", "replace")
        ).hexdigest()
        existing = self._existing_outcome(
            source_identity, content_hash, content
        )
        if existing is not None:
            return existing
        classification = await self._screen(content)
        if classification.safe:
            return IntakeOutcome(released=True, safe_content=content)
        review = self._store.quarantine(
            QuarantineRequest(
                workflow=workflow,
                source_identity=source_identity,
                content_hash=content_hash,
                policy_version=POLICY_VERSION,
                safe_content_ref=(
                    f"quarantine://{source_identity}/{content_hash[:12]}"
                ),
                classification_category=classification.category,
                card_title=card_title,
            )
        )
        return _outcome_for(review, safe_content=None)

    def _existing_outcome(
        self, source_identity: str, content_hash: str, content: str
    ) -> IntakeOutcome | None:
        """Return the prior outcome for identical content, if any (FR-021)."""
        existing_input = self._store.find_untrusted_input(
            source_identity, content_hash
        )
        if existing_input is None:
            return None
        review = self._store.find_review_for_input(existing_input.id)
        if review is None:
            return None
        if review.review_state == "released":
            return IntakeOutcome(released=True, safe_content=content)
        return _outcome_for(review, safe_content=None)

    async def _screen(self, content: str) -> ClassificationResult:
        """Deterministic bounds check, then the input-security specialist."""
        if len(content.encode("utf-8", "replace")) > self._max_bytes:
            return ClassificationResult(
                safe=False, category="oversized", reason="exceeds input bounds"
            )
        specialist = self._roster.get(_INPUT_SECURITY_ROLE)
        if specialist is None:
            return ClassificationResult(
                safe=False,
                category="unavailable",
                reason="input-security role not configured",
            )
        try:
            backend = self._backend_policy.backend_for(specialist)
        except SpecialistCapabilityError:
            return ClassificationResult(
                safe=False, category="unavailable", reason="no capable backend"
            )
        envelope = build_classification_envelope(specialist.prompt, content)
        try:
            return await classify_input(
                backend,
                envelope,
                timeout_seconds=self._classify_timeout_seconds,
            )
        except ClassificationError:
            return ClassificationResult(
                safe=False,
                category="malformed_result",
                reason="classification failed",
            )

    def release(self, review_id: str) -> SecurityReviewRecord | None:
        """Release a pending review: its content may now be trusted."""
        return self._store.resolve_review(review_id, "released")

    def discard(self, review_id: str) -> SecurityReviewRecord | None:
        """Discard a pending review: the original input is left unmodified."""
        return self._store.resolve_review(review_id, "discarded")


def _outcome_for(
    review: SecurityReviewRecord, *, safe_content: str | None
) -> IntakeOutcome:
    return IntakeOutcome(
        released=False,
        safe_content=safe_content,
        security_review_id=review.id,
        workflow_id=review.workflow_id,
        card_id=review.card_id,
    )
