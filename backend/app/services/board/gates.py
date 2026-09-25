"""Human-gate resolution and targeted downstream invalidation (feature 026,
T045, FR-016/FR-017).

A gate card is never claimed by a specialist (data-model.md "Card
States") — its own approval or rejection is the only exit from
``awaiting_human``. Approval cascades ready-dependent work the same way
an accepted specialist result does (see ``artifacts.py``); rejection
invalidates only the work that actually named this gate as a dependency,
never the whole workflow (User Story 4).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models_board import CardKind, CardState, WorkCard
from app.models_board_records import HumanGateRecord
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.dependents import advance_ready_dependents
from app.services.board.service import BoardService

_DECISION_TARGET_STATE = {
    "approved": CardState.DONE,
    "rejected": CardState.CANCELLED,
}

#: T078's three interview personas — see ``models_board.py``'s
#: ``CardKind.REFINEMENT`` and ``specialists/{requester,pm,uiux}``.
_REFINEMENT_PERSONAS = ("requester", "pm", "uiux")

#: The one logical name a gate resolution's free-text response is stored
#: under — see ``refinement.py``'s own copy of this constant (kept
#: duplicated rather than importing, since ``refinement.py`` imports
#: this module and Python has no cyclic-import escape hatch worth the
#: coupling for one string).
_RESPONSE_LOGICAL_NAME = "response"


@dataclass(frozen=True)
class GateRequirements:
    """Which gates are mandatory before other work may start (T068/T078).

    Bundled to keep :class:`GatesService`'s constructor within the
    repo's argument-count limit. Off by default — a personal/
    lightweight deployment trusts the coordinator's own judgment.
    """

    decomposition: bool = False
    prd: bool = False


class UnknownGateError(Exception):
    """Raised when a card has no gate record to resolve."""


class GatesService:
    """Creates gate cards and resolves their operator decisions."""

    def __init__(
        self,
        store: BoardStore,
        gate_store: BoardGateStore,
        board_service: BoardService,
        artifacts: ArtifactsService,
        *,
        required: GateRequirements | None = None,
    ) -> None:
        self._store = store
        self._gate_store = gate_store
        self._board_service = board_service
        self._artifacts = artifacts
        #: FR "enforced decomposition" (T068): when set, decomposition is
        #: triggered off approving ``understanding_gate`` — or
        #: ``prd_gate`` when PRD is also required (see
        #: ``_decomposition_trigger_kind``) — deterministically creating
        #: the decomposition-assessment card in code, rather than
        #: leaving that to the coordinator's own judgment — a hard
        #: guarantee needs a hard trigger, not an LLM's initiative. See
        #: ``coordinator.py``'s ``_validate`` for the other enforcement
        #: half (blocking other work until decomposition resolves).
        self._required = required or GateRequirements()

    def create_gate(
        self,
        workflow_id: str,
        *,
        kind: str,
        title: str,
        requested_decision: str,
        target_artifact_id: str | None = None,
    ) -> WorkCard:
        """Create an ``awaiting_human`` gate card and its decision record."""
        card = WorkCard(
            id=f"card-{uuid.uuid4().hex[:8]}",
            workflow_id=workflow_id,
            kind=kind,
            title=title,
            state=CardState.AWAITING_HUMAN,
        )
        self._store.create_card(card)
        self._gate_store.create_gate(
            HumanGateRecord(
                id=f"gate-{uuid.uuid4().hex[:8]}",
                card_id=card.id,
                requested_decision=requested_decision,
                target_artifact_id=target_artifact_id,
            )
        )
        return card

    def get_gate(self, card_id: str) -> HumanGateRecord | None:
        """Return *card_id*'s gate record, or ``None`` if it has none."""
        return self._gate_store.get_for_card(card_id)

    def resolve(
        self, card_id: str, decision: str, *, answer: str | None = None
    ) -> WorkCard:
        """Record the operator's *decision* and apply its consequence.

        :param decision: ``"approved"`` or ``"rejected"``.
        :param answer: Free-text response (T078) — a
            ``refinement_gate``'s answer, or a ``prd_gate`` rejection's
            feedback for `pm`'s redraft. Stored as a reference artifact
            when given; ignored for any other gate kind/decision.
        :raises UnknownGateError: If *card_id* has no gate record.
        :raises ValueError: If *decision* is not a recognized value.
        """
        if self._gate_store.get_for_card(card_id) is None:
            raise UnknownGateError(f"no gate for card: {card_id}")
        target = _DECISION_TARGET_STATE.get(decision)
        if target is None:
            raise ValueError(f"unrecognized gate decision: {decision}")
        if answer is not None:
            self._artifacts.store_reference_artifact(
                ArtifactDraft(
                    producer_card_id=card_id,
                    logical_name=_RESPONSE_LOGICAL_NAME,
                    revision=1,
                    content=answer,
                    trust="operator_approved",
                )
            )
        self._gate_store.record_decision(card_id, decision)
        card = self._board_service.transition_card(
            card_id, target.value, event_type=f"gate.{decision}"
        )
        if decision == "approved":
            self._maybe_require_refinement(card)
            self._maybe_require_decomposition(card)
            self._maybe_approve_prd(card)
            advance_ready_dependents(
                self._store, self._board_service, card.workflow_id
            )
        else:
            self._maybe_redraft_prd(card)
            self._invalidate_dependents(card.workflow_id, card_id)
        self._maybe_start_prd(card)
        return card

    def _decomposition_trigger_kind(self) -> str:
        """The gate kind whose approval starts decomposition.

        ``prd_gate`` when PRD is also required (decomposition must wait
        for the full plan), else ``understanding_gate`` as before T078.
        """
        if self._required.prd:
            return CardKind.PRD_GATE.value
        return CardKind.UNDERSTANDING_GATE.value

    def _maybe_require_decomposition(self, resolved_gate: WorkCard) -> None:
        """Deterministically create the decomposition-assessment card
        right after its trigger gate is approved, when enforced.

        A no-op for any other gate kind, when enforcement is off, or for
        a workflow whose source task is itself already a published
        decomposition child (``Workflow.skip_decomposition``) — never
        force decomposition into a child's children.
        """
        if (
            not self._required.decomposition
            or resolved_gate.kind != self._decomposition_trigger_kind()
        ):
            return
        workflow = self._store.get_workflow(resolved_gate.workflow_id)
        if workflow is None or workflow.skip_decomposition:
            return
        self._store.create_card(
            WorkCard(
                id=f"card-{uuid.uuid4().hex[:8]}",
                workflow_id=workflow.id,
                kind=CardKind.DECOMPOSITION.value,
                title="Assess decomposition",
                state=CardState.READY,
                eligible_roles=("pm",),
            )
        )

    def _maybe_require_refinement(self, understanding_gate: WorkCard) -> None:
        """Deterministically create the three persona interview cards
        right after ``understanding_gate`` is approved, when enforced.

        A no-op for any other gate kind, when enforcement is off, or for
        a workflow whose source task is itself already a published
        decomposition child — a subtask Kestrel itself scoped out has
        already had its own refinement pass at the parent's level.
        """
        if (
            not self._required.prd
            or understanding_gate.kind != CardKind.UNDERSTANDING_GATE.value
        ):
            return
        workflow = self._store.get_workflow(understanding_gate.workflow_id)
        if workflow is None or workflow.skip_decomposition:
            return
        for persona in _REFINEMENT_PERSONAS:
            self._store.create_card(
                WorkCard(
                    id=f"card-{uuid.uuid4().hex[:8]}",
                    workflow_id=workflow.id,
                    kind=CardKind.REFINEMENT.value,
                    title=f"{persona} interview questions",
                    state=CardState.READY,
                    eligible_roles=(persona,),
                )
            )

    def _maybe_start_prd(self, resolved_gate: WorkCard) -> None:
        """Create `pm`'s PRD-drafting card once every persona interview
        has reached a terminal state.

        A no-op for any other gate kind, if any interview is still
        outstanding, or if a ``prd``/``prd_gate`` already exists (belt
        and suspenders — this should only ever become true once, at the
        moment the last interview resolves). A rejected interview counts
        as terminal too: the workflow must not deadlock on one persona
        never answering.
        """
        if resolved_gate.kind != CardKind.REFINEMENT_GATE.value:
            return
        cards = self._store.list_cards(resolved_gate.workflow_id)
        interviews = [
            c for c in cards if c.kind == CardKind.REFINEMENT_GATE.value
        ]
        if not interviews or not all(
            self._is_terminal(c.state) for c in interviews
        ):
            return
        if any(
            c.kind in (CardKind.PRD.value, CardKind.PRD_GATE.value)
            for c in cards
        ):
            return
        self._store.create_card(
            WorkCard(
                id=f"card-{uuid.uuid4().hex[:8]}",
                workflow_id=resolved_gate.workflow_id,
                kind=CardKind.PRD.value,
                title="Draft PRD",
                state=CardState.READY,
                eligible_roles=("pm",),
            )
        )

    def _maybe_approve_prd(self, prd_gate: WorkCard) -> None:
        """Record the approved PRD's content on the workflow, once its
        gate is approved.

        A no-op for any other gate kind, or if the gate somehow has no
        target artifact (should not happen — ``refinement.py`` always
        sets one when creating a ``prd_gate``).
        """
        if prd_gate.kind != CardKind.PRD_GATE.value:
            return
        gate = self._gate_store.get_for_card(prd_gate.id)
        if gate is None or gate.target_artifact_id is None:
            return
        content = self._artifacts.read_content(gate.target_artifact_id)
        if content is not None:
            self._store.record_approved_prd(prd_gate.workflow_id, content)

    def _maybe_redraft_prd(self, prd_gate: WorkCard) -> None:
        """Deterministically create a fresh ``prd`` card after a
        ``prd_gate`` rejection, so the workflow never deadlocks on one.

        Unconditional on rejection (not gated behind ``required.prd``):
        once a ``prd_gate`` exists at all, redrafting is the sensible
        default regardless of how enforcement is configured now. A
        no-op for any other gate kind.
        """
        if prd_gate.kind != CardKind.PRD_GATE.value:
            return
        self._store.create_card(
            WorkCard(
                id=f"card-{uuid.uuid4().hex[:8]}",
                workflow_id=prd_gate.workflow_id,
                kind=CardKind.PRD.value,
                title="Redraft PRD",
                state=CardState.READY,
                eligible_roles=("pm",),
            )
        )

    def _invalidate_dependents(self, workflow_id: str, gate_id: str) -> None:
        """Cancel only the not-yet-terminal cards that depended on *gate_id*."""
        relations = self._store.list_relations(workflow_id)
        dependents = {
            r.card_id for r in relations if r.depends_on_card_id == gate_id
        }
        for card in self._store.list_cards(workflow_id):
            if card.id not in dependents or card.id == gate_id:
                continue
            if not self._is_terminal(card.state):
                self._board_service.transition_card(
                    card.id,
                    CardState.CANCELLED.value,
                    event_type="gate.rejected_dependent_cancelled",
                )

    @staticmethod
    def _is_terminal(state: str) -> bool:
        return CardState(state) in {
            CardState.DONE,
            CardState.FAILED,
            CardState.CANCELLED,
        }
