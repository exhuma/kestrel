"""What each gate's announcement is made of (feature 046).

Reads a gate's content from the board (the restatement, the PRD, the
interview's answers, the executive summary, the question counts) and
pairs it with the builder that words it and the key that makes it
at-most-once.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.documents import Document, Text, document, paragraph
from app.models_board import CardKind, WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.announcements import gates as words
from app.services.board.announcements.common import Context
from app.services.board.artifacts import ArtifactsService
from app.services.board.estimation import SUMMARY_LOGICAL_NAME
from app.services.board.gates import GatesService
from app.services.board.interview_batch import (
    InterviewBoard,
    batch,
    gates_by_producer,
    plan_id_of,
    questions_of,
)
from app.services.board.specialists import SpecialistRoster

_UNAVAILABLE = document(paragraph(Text(
    "(The content is not shown here. Open the request in kestrel.)"
)))


@dataclass(frozen=True)
class Plan:
    """One announcement to make: its ledger key, and how to word it for
    the people on the ticket."""

    key: str
    build: Callable[[Context], Document]


class GateContent:
    """Turns an opened gate into the announcement it calls for."""

    def __init__(
        self,
        store: BoardStore,
        gates: GatesService,
        artifacts: ArtifactsService,
        roster: SpecialistRoster,
    ) -> None:
        self._store = store
        self._gates = gates
        self._artifacts = artifacts
        self._roster = roster
        self._board = InterviewBoard(store, gates.get_gate, artifacts)

    def plan(self, card: WorkCard) -> Plan | None:
        """The announcement for the gate *card*, or ``None`` for a card
        that is not a gate with something to say."""
        make = {
            CardKind.UNDERSTANDING_GATE.value: self._understanding,
            CardKind.STRATEGIC_INTERVIEW_GATE.value: self._strategic,
            CardKind.REFINEMENT_GATE.value: self._refinement,
            CardKind.PRD_GATE.value: self._prd,
            CardKind.CAB1_GATE.value: self._cab1,
            CardKind.DECOMPOSITION_GATE.value: self._cab2,
        }.get(card.kind)
        return make(card) if make is not None else None

    def _understanding(self, card: WorkCard) -> Plan:
        restatement = self._target_document(card)
        return Plan(
            f"gate_opened:{card.id}",
            lambda ctx: words.understanding(ctx, restatement),
        )

    def _prd(self, card: WorkCard) -> Plan:
        requirements = self._target_document(card)
        return Plan(
            f"gate_opened:{card.id}",
            lambda ctx: words.prd(ctx, requirements),
        )

    def _strategic(self, card: WorkCard) -> Plan:
        count = self._question_count(card)
        return Plan(
            f"gate_opened:{card.id}",
            lambda ctx: words.strategic_interview(ctx, count),
        )

    def _cab1(self, card: WorkCard) -> Plan:
        target = self._target_id(card)
        text = self._artifacts.read_content(target) if target else None
        answers = words.answers_as_blocks(text or "")
        return Plan(
            f"gate_opened:{card.id}",
            lambda ctx: words.cab_strategic_fit(ctx, answers),
        )

    def _cab2(self, card: WorkCard) -> Plan:
        summary = (
            self._artifacts.latest_document_for_card(
                card.id, SUMMARY_LOGICAL_NAME
            )
            or _UNAVAILABLE
        )
        return Plan(
            f"gate_opened:{card.id}",
            lambda ctx: words.cab_summary(ctx, summary),
        )

    def _refinement(self, card: WorkCard) -> Plan:
        """One plan for the whole batch the gate belongs to: the key is
        the interview plan's, so every gate of the batch shares it."""
        producer = self._producer(card)
        plan_id = plan_id_of(self._board, producer) if producer else None
        asks = self._asks(card.workflow_id, plan_id)
        return Plan(
            f"gate_opened:batch:{plan_id or card.workflow_id}",
            lambda ctx: words.refinement_batch(ctx, asks),
        )

    def _asks(
        self, workflow_id: str, plan_id: str | None
    ) -> list[words.InterviewAsk]:
        gates = gates_by_producer(self._board, workflow_id)
        asks = []
        for member in batch(self._board, workflow_id, plan_id):
            if member.id not in gates:
                continue
            persona = member.eligible_roles[0] if member.eligible_roles else ""
            asks.append(words.InterviewAsk(
                self._label(persona), len(questions_of(self._board, member))
            ))
        return asks

    def _label(self, persona: str) -> str:
        specialist = self._roster.get(persona)
        return specialist.label if specialist is not None else persona

    def _target_id(self, card: WorkCard) -> str | None:
        record = self._gates.get_gate(card.id)
        return record.target_artifact_id if record is not None else None

    def _target_document(self, card: WorkCard) -> Document:
        target = self._target_id(card)
        found = self._artifacts.read_document(target) if target else None
        return found or _UNAVAILABLE

    def _producer(self, card: WorkCard) -> WorkCard | None:
        target = self._target_id(card)
        producer = self._artifacts.producer_card_id(target) if target else None
        return self._store.get_card(producer) if producer else None

    def _question_count(self, card: WorkCard) -> int:
        producer = self._producer(card)
        return len(questions_of(self._board, producer)) if producer else 0
