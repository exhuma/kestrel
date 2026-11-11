"""The fail-closed untrusted-input boundary (feature 026, FR-018..FR-023).

Every external or human-gate input — a task body, feedback item, gate
edit, questionnaire answer, or direct session prompt — passes through
:class:`QuarantineService` before it can reach an agent, a workflow
transition, or a task-source write. Oversized content, a missing/
incapable input-security specialist, and any malformed or timed-out
classification all fail closed into quarantine (FR-020); nothing here
ever treats an unclear result as safe.

This is a system boundary (constitution Principle VI): untrusted content
arrives as a ``Document`` and is rendered to Markdown here, once, to be
bounded, hashed and classified by the input-security agent.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from app.document_formats.markdown import render_markdown
from app.documents import Document
from app.models_board import Workflow
from app.models_board_records import IntakeOutcome, SecurityReviewRecord
from app.persistence.board_quarantine_store import (
    BoardQuarantineStore,
    QuarantineRequest,
    ReviewResolution,
)
from app.services.board import decision_log
from app.services.board.dispatch import (
    ClassificationError,
    ClassificationResult,
    build_classification_envelope,
    classify_input,
)
from app.services.board.liaison import ChoosesBackend, without_marker
from app.services.board.specialists import SpecialistRoster

#: Bumped when the deterministic screening/classification policy changes.
POLICY_VERSION = "v2"

_logger = logging.getLogger("kestrel.board.quarantine")

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
    body: Document


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
    content: Document
    workflow: Workflow | None = None
    #: What the content is, in one sentence, for the screening.
    context: str = ""
    #: The reply marker, removed before screening: it is not the reply.
    marker: str = ""


@dataclass(frozen=True)
class _Screening:
    """One piece of content to screen, and what to record if it is held."""

    workflow: Workflow | None
    source_identity: str
    content: Document
    card_title: str
    context: str = ""
    marker: str = ""


class QuarantineService:
    """Screens untrusted input and records/resolves quarantine decisions."""

    def __init__(
        self,
        quarantine_store: BoardQuarantineStore,
        roster: SpecialistRoster,
        backend_policy: ChoosesBackend,
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
        return await self._intake(_Screening(
            workflow=None,
            source_identity=f"{intake.source}:{intake.task_ref}",
            content=intake.body,
            card_title=f"Security review: {intake.task_ref}",
        ))

    async def intake_for_existing_workflow(
        self, intake: ExistingWorkflowIntake
    ) -> IntakeOutcome:
        """Screen content targeting existing work (feedback/gate input/
        direct prompt)."""
        identity_base = (
            intake.workflow.id if intake.workflow is not None
            else intake.identity_ref
        )
        return await self._intake(_Screening(
            workflow=intake.workflow,
            source_identity=f"{identity_base}:{intake.category}",
            content=intake.content,
            card_title=f"Security review: {intake.category}",
            context=intake.context,
            marker=intake.marker,
        ))

    async def _intake(self, screening: _Screening) -> IntakeOutcome:
        content = screening.content
        text = render_markdown(content)
        content_hash = hashlib.sha256(
            text.encode("utf-8", "replace")
        ).hexdigest()
        existing = self._existing_outcome(
            screening.source_identity, content_hash, content
        )
        if existing is not None:
            return existing
        classification = await self._screen(
            without_marker(text, screening.marker), screening
        )
        decision_log.screened(
            screening.source_identity, classification.safe,
            classification.category, classification.reason,
        )
        if classification.safe:
            return IntakeOutcome(released=True, safe_content=content)
        review = self._store.quarantine(
            QuarantineRequest(
                workflow=screening.workflow,
                source_identity=screening.source_identity,
                content_hash=content_hash,
                policy_version=POLICY_VERSION,
                safe_content_ref=(
                    f"quarantine://{screening.source_identity}/"
                    f"{content_hash[:12]}"
                ),
                classification_category=classification.category,
                reason=classification.reason,
                card_title=screening.card_title,
            )
        )
        return _outcome_for(review, safe_content=None)

    def _existing_outcome(
        self, source_identity: str, content_hash: str, content: Document
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

    async def _screen(
        self, content: str, screening: _Screening
    ) -> ClassificationResult:
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
        backend = self._backend_policy.backend_for(specialist)
        envelope = build_classification_envelope(
            specialist.prompt, content, screening.context
        )
        try:
            return await classify_input(
                backend,
                envelope,
                timeout_seconds=self._classify_timeout_seconds,
            )
        except ClassificationError as exc:
            _logger.warning(
                "input-security classification failed for %s: %s",
                screening.source_identity,
                exc,
            )
            return ClassificationResult(
                safe=False,
                category=exc.category,
                reason=self._failure_reason(exc.category),
            )

    def _failure_reason(self, category: str) -> str:
        """Why a classification that never produced a verdict failed —
        never the untrusted content, never raw backend output (#66)."""
        if category == "timeout":
            return (
                "the input-security check did not finish within "
                f"{self._classify_timeout_seconds:g}s "
                "(the reasoning timeout_seconds)"
            )
        if category == "content_filter":
            return (
                "the AI provider's content filter blocked the "
                "input-security check"
            )
        if category == "backend_error":
            return "the input-security backend failed; see the kestrel log"
        return "the input-security result could not be read"

    def review_for_card(self, card_id: str) -> SecurityReviewRecord | None:
        """Return the review gating *card_id*, if any (board-view lookup —
        lets the frontend address ``/security-reviews/{id}/resolve``
        without the card DTO carrying anything unsafe)."""
        return self._store.find_review_for_card(card_id)

    def release(self, review_id: str) -> ReviewResolution | None:
        """Release a pending review: its content may now be trusted."""
        return self._store.resolve_review(review_id, "released")

    def discard(self, review_id: str) -> ReviewResolution | None:
        """Discard a pending review: the original input is left unmodified."""
        return self._store.resolve_review(review_id, "discarded")


def _outcome_for(
    review: SecurityReviewRecord, *, safe_content: Document | None
) -> IntakeOutcome:
    return IntakeOutcome(
        released=False,
        safe_content=safe_content,
        security_review_id=review.id,
        workflow_id=review.workflow_id,
        card_id=review.card_id,
    )
