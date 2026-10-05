"""Turning a screened reply into a decision (feature 046, User Story 3).

The last two steps of handling a reply (``replies.py``): the liaison says
what it means, and a clear approve or reject resolves the gate through
``GatesService.resolve``, exactly as the UI does, credited to the reply's
author. Anything the liaison could not read cleanly, and a rejection
without the reason the decision needs, are asked back instead: nothing is
ever decided on a guess.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from app.documents import Document
from app.models_board import WorkCard
from app.persistence.comment_store import Outcome
from app.ports import Person
from app.services.board.announcements import replies as answers
from app.services.board.announcements.common import Context
from app.services.board.gate_decision import Decider, ReasonRequiredError
from app.services.board.gates import GatesService
from app.services.board.interview_answers import GateNotOpenError
from app.services.board.liaison import (
    APPROVE,
    REJECT,
    Interpretation,
    LiaisonAsk,
)
from app.services.board.reply_rules import OpenedGate


class ReadsReplies(Protocol):
    """What reads a reply's meaning (``LiaisonService``)."""

    async def interpret(self, ask: LiaisonAsk) -> Interpretation: ...


@dataclass(frozen=True)
class Settled:
    """How a reply was settled, and the answer to post on the ticket.

    :param decided: The gate the reply decided and how, when it did.
    """

    outcome: Outcome
    build: Callable[[Context], Document]
    decided: tuple[WorkCard, str] | None = None


@dataclass(frozen=True)
class Reading:
    """A screened reply to read, and who wrote it where."""

    ask: LiaisonAsk
    author: Person
    channel: str
    external_id: str


#: How the gate is told about a past decision instead (``replies.py``).
Past = Callable[[OpenedGate, Person], Settled]

_DECISIONS = {APPROVE: "approved", REJECT: "rejected"}


class ReplyDecider:
    """Reads a screened reply and decides its gate when it is clear."""

    def __init__(self, gates: GatesService, liaison: ReadsReplies) -> None:
        self._gates = gates
        self._liaison = liaison

    async def decide(
        self, gate: OpenedGate, reading: Reading, past: Past
    ) -> Settled:
        """Decide *gate* from *reading*, or say why not."""
        meaning = await self._liaison.interpret(reading.ask)
        decision = _DECISIONS.get(meaning.intent)
        if decision is None:
            return _asked_back(gate, reading, meaning.reason_missing)
        answer = meaning.reason if decision == "rejected" else ""
        try:
            card = self._gates.resolve(
                gate.card.id, decision, answer=answer or None,
                decided_by=Decider(
                    reading.channel, reading.author.account_id,
                    reading.author.display_name, reading.external_id,
                ),
            )
        except GateNotOpenError:
            return past(gate, reading.author)
        except ReasonRequiredError:
            return _asked_back(gate, reading, reason_missing=True)
        return _confirmed(card, reading, decision, meaning.intent)


def _asked_back(
    gate: OpenedGate, reading: Reading, reason_missing: bool
) -> Settled:
    author, words = reading.author, reading.ask.decision
    return Settled(
        Outcome("unclear", gate_card_id=gate.card.id, intent="unclear"),
        lambda ctx: answers.asked_back(
            ctx, author, words, reason_missing=reason_missing
        ),
    )


def _confirmed(
    card: WorkCard, reading: Reading, decision: str, intent: str
) -> Settled:
    author, kind = reading.author, card.kind
    return Settled(
        Outcome("decided", gate_card_id=card.id, intent=intent),
        lambda ctx: answers.confirmed(
            ctx, author, kind, decision == "approved"
        ),
        decided=(card, decision),
    )
