"""What a request is doing right now, in one state (feature 033).

The board holds every card's state, but an operator needs one answer:
is anything happening, and if not, why not? This derives it, purely,
from the request's cards, its latest events, and the live work this
process is running for it (``live_activity.py``). Precedence (FR-002):
working > a failed card > waiting for you > a failed turn > queued >
done or cancelled > stalled. Done and cancelled are the request's derived
outcome (``phases.outcome_of``, feature 040), never "every card is
terminal". A failed *card* needs the operator; a failed *turn* is
retried on its own and must not hide a decision that is waiting on them.

The result names *who* and *what*; it never phrases a sentence — the
frontend does (constitution Principle II keeps the decision here, the
wording there).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models_board import CardKind, CardState, WorkCard
from app.models_board_records import BoardEventRecord
from app.services.board.intake import SCREENING_TITLE
from app.services.board.live_activity import LiveTurn

#: Event types recording a failed agent turn (``BoardService.record_problem``).
PROBLEM_EVENTS = frozenset({"card.turn_failed", "coordinator.turn_failed"})

#: Outcomes that end a request: it reports them as its activity.
_FINISHED = frozenset({"done", "cancelled"})

_WAITING_STATES = frozenset(
    {CardState.AWAITING_HUMAN.value, CardState.QUARANTINED.value}
)


@dataclass(frozen=True)
class RequestActivity:
    """One request's activity.

    :param state: ``working``, ``problem``, ``waiting``, ``queued``,
        ``done``, ``cancelled`` or ``stalled``.
    :param actor: Who is working, or who the queued work is for.
    :param subject: The card concerned, by title.
    :param detail: For ``problem``: the recorded, safe reason.
    :param reason: For ``stalled``: why, as a code —
        ``interrupted_screening``, ``interrupted_claim`` or
        ``nothing_ready``.
    :param since: When this state began, as far as is known (UTC).
    :param tool: For ``working``: the last tool called (feature 036).
    :param tool_calls: For ``working``: how many tool calls so far.
    """

    state: str
    actor: str | None = None
    subject: str | None = None
    detail: str | None = None
    reason: str | None = None
    since: datetime | None = None
    tool: str | None = None
    tool_calls: int | None = None


@dataclass(frozen=True)
class ActivityInputs:
    """Everything :func:`activity_of` reads, bundled to stay within the
    repo's argument-count limit.

    :param outcome: The request's outcome (``phases.outcome_of``).
    :param labels: Specialist id -> display label.
    """

    cards: list[WorkCard]
    events: list[BoardEventRecord]
    live: LiveTurn | None
    outcome: str
    labels: dict[str, str]


def activity_of(inputs: ActivityInputs) -> RequestActivity:
    """The request's activity, by FR-002's precedence."""
    live = inputs.live
    if live is not None:
        return RequestActivity(
            "working", actor=live.actor, subject=live.subject,
            since=_utc(live.started_at), tool=live.tool,
            tool_calls=live.tool_calls or None,
        )
    for derive in (_failed_card, _waiting, _failed_turn, _queued):
        found = derive(inputs)
        if found is not None:
            return found
    if inputs.outcome in _FINISHED:
        return RequestActivity(
            inputs.outcome, since=_latest_time(inputs.events)
        )
    return _stalled(inputs)


def _failed_card(inputs: ActivityInputs) -> RequestActivity | None:
    card = next(
        (c for c in inputs.cards if c.state == CardState.FAILED.value), None
    )
    if card is None:
        return None
    return RequestActivity(
        "problem", actor=_actor(card, inputs.labels), subject=card.title,
        since=_card_time(card, inputs.events),
    )


def _failed_turn(inputs: ActivityInputs) -> RequestActivity | None:
    latest = inputs.events[-1] if inputs.events else None
    if latest is None or latest.event_type not in PROBLEM_EVENTS:
        return None
    card = _card(inputs.cards, latest.card_id)
    return RequestActivity(
        "problem",
        actor="coordinator" if card is None else _actor(card, inputs.labels),
        subject=card.title if card is not None else None,
        detail=_detail(latest),
        since=_utc(latest.created_at),
    )


def _waiting(inputs: ActivityInputs) -> RequestActivity | None:
    card = next(
        (c for c in inputs.cards if c.state in _WAITING_STATES), None
    )
    if card is None:
        return None
    return RequestActivity(
        "waiting", subject=card.title, since=_card_time(card, inputs.events)
    )


def _queued(inputs: ActivityInputs) -> RequestActivity | None:
    card = next((c for c in inputs.cards if _claimable(c)), None)
    if card is None:
        return None
    return RequestActivity(
        "queued", actor=_actor(card, inputs.labels), subject=card.title,
        since=_card_time(card, inputs.events),
    )


def _stalled(inputs: ActivityInputs) -> RequestActivity:
    claimed = next(
        (c for c in inputs.cards if c.state == CardState.CLAIMED.value), None
    )
    if claimed is None:
        reason = "nothing_ready"
    elif claimed.title == SCREENING_TITLE:
        reason = "interrupted_screening"
    else:
        reason = "interrupted_claim"
    return RequestActivity(
        "stalled",
        subject=claimed.title if claimed is not None else None,
        reason=reason,
        since=_latest_time(inputs.events),
    )


def _claimable(card: WorkCard) -> bool:
    """Ready work for a specialist — or a delivery the system runs."""
    if card.state != CardState.READY.value:
        return False
    return bool(card.eligible_roles) or card.kind == CardKind.DELIVERY.value


def _actor(card: WorkCard, labels: dict[str, str]) -> str | None:
    if not card.eligible_roles:
        return None
    role = card.eligible_roles[0]
    return labels.get(role, role)


def _card(cards: list[WorkCard], card_id: str | None) -> WorkCard | None:
    return next((c for c in cards if c.id == card_id), None)


def _detail(event: BoardEventRecord) -> str | None:
    try:
        detail = json.loads(event.payload).get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) else None


def _card_time(
    card: WorkCard, events: list[BoardEventRecord]
) -> datetime | None:
    """When *card* last changed, or the request did, as a fallback."""
    for event in reversed(events):
        if event.card_id == card.id:
            return _utc(event.created_at)
    return _latest_time(events)


def _latest_time(events: list[BoardEventRecord]) -> datetime | None:
    return _utc(events[-1].created_at) if events else None


def _utc(moment: datetime | None) -> datetime | None:
    """Stored times are naive UTC (constitution: persistence); make them
    explicit so a browser never reads them as local time."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=timezone.utc)
