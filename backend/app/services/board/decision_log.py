"""What kestrel decided on the board, and why, in one logger.

``kestrel.board.decisions`` writes one INFO line per decision: a card
claimed and finished, what the coordinator did, a verification's findings
and round, an escalation opened, delivery requested or held and by what,
a screening result, and how a ticket reply was read. Following one request
is a filter on its ``workflow_id`` (a field of every record in JSON logs).

Each line carries short summaries kestrel produced itself (a finding's
summary, a screening reason), never a prompt or a ticket's text: those
are in ``kestrel.reasoning`` and ``kestrel.agent`` at DEBUG.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from app.models_board import WorkCard
from app.models_board_records import CoordinatorActionRecord

_log = logging.getLogger("kestrel.board.decisions")

#: The most of one summary a line keeps.
_SUMMARY = 200


def _short(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _SUMMARY else f"{flat[:_SUMMARY]}…"


def _info(workflow_id: str, card_id: str | None, message: str) -> None:
    _log.info(
        "workflow=%s %s", workflow_id, message,
        extra={"workflow_id": workflow_id, "card_id": card_id},
    )


def card_claimed(card: WorkCard, role: str, runs_on: str) -> None:
    """A role took a card, and where its turn runs."""
    _info(
        card.workflow_id, card.id,
        f"card claimed: {card.kind} {card.id} by {role} on {runs_on} "
        f"(attempt {card.attempt_count})",
    )


def card_finished(card: WorkCard, role: str) -> None:
    """A role's turn on a card gave a result."""
    _info(
        card.workflow_id, card.id,
        f"card finished: {card.kind} {card.id} by {role}",
    )


def coordinator_acted(
    workflow_id: str, records: Iterable[CoordinatorActionRecord]
) -> None:
    """Each action the coordinator proposed, and whether it was applied."""
    for record in records:
        action = record.action
        what = ", ".join(
            f"{key}={_short(str(value))}" for key, value in action.items()
            if value not in (None, "", [], ())
        )
        outcome = (
            "applied" if record.applied
            else f"rejected ({record.rejection_reason or 'no reason'})"
        )
        _info(workflow_id, None, f"coordinator action {outcome}: {what}")


def verified(
    card: WorkCard, findings: list[tuple[str, str]], round_of: str
) -> None:
    """A verification's findings (category, summary), and its round."""
    if not findings:
        _info(
            card.workflow_id, card.id,
            f"verification {card.id}{round_of}: clean",
        )
        return
    listed = "; ".join(f"{cat}: {_short(text)}" for cat, text in findings)
    _info(
        card.workflow_id, card.id,
        f"verification {card.id}{round_of}: {len(findings)} finding(s): "
        f"{listed}",
    )


def escalation_opened(workflow_id: str, gate: WorkCard) -> None:
    """A problem was put to a person (``escalation_gate`` and kin)."""
    _info(
        workflow_id, gate.id,
        f"escalation opened: {gate.kind} {gate.id}: {_short(gate.title)}",
    )


def delivery(
    workflow_id: str, holding: list[WorkCard], requested: bool
) -> None:
    """Whether a clean verification led to delivery, and what holds it."""
    if requested:
        _info(workflow_id, None, "delivery requested")
        return
    cards = ", ".join(f"{c.kind} {c.id} ({c.state})" for c in holding)
    _info(workflow_id, None, f"delivery held by: {cards or 'unverified work'}")


def screened(identity: str, safe: bool, category: str, reason: str) -> None:
    """A screening's verdict on untrusted input."""
    verdict = "released" if safe else "held"
    _log.info(
        "input %s %s: %s (%s)", identity, verdict, category, _short(reason)
    )


def reply_read(
    workflow_id: str, gate: WorkCard, intent: str, reason: str
) -> None:
    """How a reply on the ticket was read."""
    because = f": {_short(reason)}" if reason else ""
    _info(
        workflow_id, gate.id,
        f"reply on {gate.kind} {gate.id} read as {intent}{because}",
    )


def unreadable(card: WorkCard, reason: str, *, retrying: bool) -> None:
    """A card's result could not be read: tried again, or escalated."""
    next_step = "trying again" if retrying else "escalated"
    _info(
        card.workflow_id, card.id,
        f"result of {card.kind} {card.id} unreadable ({_short(reason)}); "
        f"{next_step}",
    )
