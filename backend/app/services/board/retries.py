"""Another attempt at work whose result could not be read (feature 042).

A card's result is accepted before it is parsed, so an unreadable one —
malformed JSON, a missing block — leaves a done card and nothing to act
on. Such work is tried again as a fresh card of the same kind that
records the attempt it replaces (``source_card_id``), and is told why
the previous one could not be read. Up to
``board_unreadable_retry_cap`` attempts happen on their own; after that
the result is escalated to the coordinator, and the operator can retry
it from the escalation.

A replaced attempt does not count as an attempt of its own: interview
rounds and understanding drafts are counted over :func:`live_attempts`.
"""
from __future__ import annotations

import json
import uuid

from app.models_board import (
    CardKind,
    CardRelation,
    CardState,
    RelationKind,
    WorkCard,
)
from app.persistence.board_store import BoardStore

#: Events that start another attempt, carrying why in their ``detail``.
AUTOMATIC = "card.unreadable_retry"
BY_OPERATOR = "intervention.retry"
_MAX_DETAIL = 500


class UnreadableResultError(Exception):
    """Raised by a result route when a card's result cannot be read.

    :param title: The escalation's title, should it come to that.
    :param reason: What was wrong, for the next attempt's prompt.
    """

    def __init__(self, title: str, reason: str) -> None:
        super().__init__(title)
        self.title = title
        self.reason = reason


def live_attempts(cards: list[WorkCard]) -> list[WorkCard]:
    """*cards* without the attempts another attempt replaced."""
    replaced = {
        c.source_card_id for c in cards
        if c.source_card_id and c.kind != CardKind.COORDINATOR_REVIEW.value
    }
    return [c for c in cards if c.id not in replaced]


def retries_of(card: WorkCard, cards: list[WorkCard]) -> int:
    """How many attempts before *card* were replaced by another."""
    by_id = {c.id: c for c in cards}
    count = 0
    source = by_id.get(card.source_card_id or "")
    while source is not None and source.kind == card.kind:
        count += 1
        source = by_id.get(source.source_card_id or "")
    return count


def retry_card(store: BoardStore, card: WorkCard) -> WorkCard:
    """Create another attempt at *card*'s work: a ready card of the same
    kind, with its roles, permission, task and dependencies."""
    attempt = WorkCard(
        id=f"card-{uuid.uuid4().hex[:8]}",
        workflow_id=card.workflow_id,
        kind=card.kind,
        title=card.title,
        state=CardState.READY.value,
        eligible_roles=card.eligible_roles,
        workspace_permission=card.workspace_permission,
        attempt_limit=card.attempt_limit,
        task_node_id=card.task_node_id,
        source_card_id=card.id,
    )
    store.create_card(attempt)
    for relation in store.list_relations(card.workflow_id):
        if (
            relation.card_id == card.id
            and relation.kind == RelationKind.DEPENDENCY
        ):
            store.add_relation(
                CardRelation(attempt.id, relation.depends_on_card_id),
                created_by_action="retry",
            )
    return attempt


def detail_of(reason: str) -> str:
    """The event payload recording why an attempt was made."""
    return json.dumps({"detail": reason[:_MAX_DETAIL]})


def retry_context(card: WorkCard, store: BoardStore) -> str:
    """What a retried card's prompt adds: why its previous attempt could
    not be used. ``""`` for any other card."""
    if not card.source_card_id or card.kind == CardKind.COORDINATOR_REVIEW:
        return ""
    reason = next(
        (
            _detail(e.payload)
            for e in reversed(store.list_events(card.workflow_id))
            if e.card_id == card.id and e.event_type in (AUTOMATIC, BY_OPERATOR)
        ),
        "",
    )
    return (
        "Your previous attempt at this card could not be used"
        + (f": {reason}" if reason else ".")
        + "\nDo the work again, and answer in exactly the format asked for."
    )


def _detail(payload: str) -> str:
    try:
        detail = json.loads(payload).get("detail")
    except (ValueError, AttributeError):
        return ""
    return detail if isinstance(detail, str) else ""
