"""HTTP routes for board-domain interventions (feature 026).

Scoped to the one intervention this MVP slice's Independent Test needs to
be operator-drivable end-to-end: releasing or discarding a quarantined
security review (US1 AC3/AC4, FR-022). The full board REST/SSE surface
(workflow/card listing, live updates, other interventions) is a later
phase (US6).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.schemas import QuarantineInterventionIn, SecurityReviewOut
from app.services.board.bootstrap import get_quarantine_service
from app.services.board.quarantine import QuarantineService

router = APIRouter(prefix="/api/board")


@router.post(
    "/security-reviews/{review_id}/resolve",
    response_model=SecurityReviewOut,
)
async def resolve_security_review(
    review_id: str,
    body: QuarantineInterventionIn,
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> SecurityReviewOut:
    """Release or discard a pending quarantine review.

    Release records a new decision permitting the content to be trusted;
    discard leaves the original input unmodified (FR-022). Both are
    idempotent no-ops on an already-resolved review's terminal state —
    the store still returns the review's current recorded state.

    :raises HTTPException: 404 if ``review_id`` is unknown.
    """
    if body.action == "release_quarantine":
        review = quarantine.release(review_id)
    else:
        review = quarantine.discard(review_id)
    if review is None:
        raise HTTPException(
            status_code=404, detail="unknown security review"
        )
    return SecurityReviewOut(
        id=review.id,
        card_id=review.card_id,
        workflow_id=review.workflow_id,
        classification_category=review.classification_category,
        review_state=review.review_state,
        resolution=review.resolution,
    )
