"""The screening card: what a newly picked-up request shows while its
input is screened (feature 032, #68, research R2).

A request exists on the board from the moment kestrel picks up its
ticket, before the input-security specialist has answered — otherwise a
slow model leaves the board empty and kestrel looks idle. Its first card
is a ``security_review`` titled "Screening input", claimed by no one:
the system itself is working it. Passing screening completes it;
quarantine cancels it, and the quarantine's own review card joins the
same request.
"""
from __future__ import annotations

import uuid

from app.models_board import CardKind, CardState, WorkCard, Workflow

#: How a screening card is recognised — it is the one ``security_review``
#: card intake itself creates.
SCREENING_TITLE = "Screening input"


def screening_card(workflow_id: str) -> WorkCard:
    """An in-progress screening card no specialist can claim."""
    return WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=workflow_id,
        kind=CardKind.SECURITY_REVIEW.value,
        title=SCREENING_TITLE,
        state=CardState.CLAIMED.value,
    )


def open_screening_card(cards: list[WorkCard]) -> WorkCard | None:
    """The request's screening card, if screening has not finished."""
    return next(
        (
            c for c in cards
            if c.kind == CardKind.SECURITY_REVIEW.value
            and c.title == SCREENING_TITLE
            and c.state == CardState.CLAIMED.value
        ),
        None,
    )


def awaits_release(workflow: Workflow, cards: list[WorkCard]) -> bool:
    """Whether *workflow* is an intake held by quarantine: screened, not
    passed, and not yet continued (FR-005). A pre-032 quarantine
    placeholder (state ``"quarantined"``) never is — its ticket is
    screened again by the next poll instead."""
    if workflow.state == "quarantined" or workflow.task_body:
        return False
    if open_screening_card(cards) is not None:
        return False
    return not any(
        c.kind == CardKind.UNDERSTANDING.value for c in cards
    )
