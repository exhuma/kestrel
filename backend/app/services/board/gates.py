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
from app.services.board.coordinator import CoordinatorService
from app.services.board.dependents import advance_ready_dependents
from app.services.board.materialise import (
    MaterialiseTarget,
    materialise_decomposition,
)
from app.services.board.prd_redraft import maybe_redraft_prd
from app.services.board.refinement_rounds import (
    has_any_round,
    maybe_advance_round,
    round_of_gate,
    still_pending,
)
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
    cab1: bool = False
    #: The CAB-1 strategic interview's hard question cap (feature 027).
    #: Only meaningful when ``cab1`` is set; carried here rather than as
    #: its own ``GatesService`` constructor argument to stay within the
    #: repo's argument-count limit.
    cab1_interview_max_questions: int = 3
    #: Max refinement-interview rounds per persona (feature 028). ``1``
    #: preserves today's exact one-round behavior.
    refinement_round_cap: int = 1
    #: Max PRD redraft attempts per workflow after a rejection (feature
    #: 028). ``1`` allows exactly one redraft before escalating.
    prd_redraft_cap: int = 1
    #: Routes a ``prd_gate`` rejection's fix-vs-reinterview triage
    #: (feature 028) through the coordinator's own judgment rather than
    #: a deterministic redraft. Carried here, not as its own
    #: ``GatesService`` constructor argument, for the same
    #: argument-count reason as the rest of this dataclass. ``None``
    #: falls back to the pre-028 behavior (unconditional, uncapped
    #: redraft) — mirrors how ``DispatchServices.coordinator`` is
    #: optional elsewhere in this codebase, so callers that don't need
    #: PRD-redraft enforcement (most existing tests) don't need one.
    coordinator: CoordinatorService | None = None


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

    @property
    def cab1_interview_max_questions(self) -> int:
        """The CAB-1 strategic interview's configured question cap."""
        return self._required.cab1_interview_max_questions

    @property
    def refinement_round_cap(self) -> int:
        """The configured max interview rounds per persona."""
        return self._required.refinement_round_cap

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

    def gate_round(self, card: WorkCard, cards: list[WorkCard]) -> int | None:
        """The 1-based interview round *card* belongs to (board API A3),
        or ``None`` if it is not a round-capped ``refinement_gate``."""
        return round_of_gate(card, cards, self.get_gate, self._artifacts)

    def mark_refinement_satisfied(self, card: WorkCard) -> None:
        """Complete one persona's interview directly, with no gate
        (feature 028) — the persona signaled it needs no further round.

        Unlike a resolved gate, this is never triggered by an operator
        action, so it re-runs the same "maybe every persona is now
        done" check :meth:`resolve` runs after every gate decision —
        otherwise a workflow whose *last* persona finishes this way
        would never see its PRD card get created.
        """
        done = self._board_service.transition_card(
            card.id, CardState.DONE.value, event_type="refinement.satisfied"
        )
        self._maybe_start_prd(done)

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
            self._maybe_require_cab1_interview(card)
            self._maybe_require_cab1_decision(card)
            self._maybe_require_refinement(card)
            self._maybe_advance_refinement_round(card)
            self._maybe_require_decomposition(card)
            self._maybe_approve_prd(card)
            self._maybe_materialise(card)
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

    def _refinement_trigger_kind(self) -> str:
        """The gate kind whose approval starts refinement.

        ``cab1_gate`` when CAB-1 is required (refinement must wait for a
        strategic go), else ``understanding_gate`` as before feature 027.
        """
        if self._required.cab1:
            return CardKind.CAB1_GATE.value
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

    def _maybe_require_cab1_interview(self, resolved_gate: WorkCard) -> None:
        """Deterministically create the strategic-interview card right
        after ``understanding_gate`` is approved, when CAB-1 is enforced.

        A no-op for any other gate kind, when CAB-1 enforcement is off, or
        for a workflow whose source task is itself already a published
        decomposition child (same subtask exemption as
        :meth:`_maybe_require_refinement`).
        """
        if (
            not self._required.cab1
            or resolved_gate.kind != CardKind.UNDERSTANDING_GATE.value
        ):
            return
        workflow = self._store.get_workflow(resolved_gate.workflow_id)
        if workflow is None or workflow.skip_decomposition:
            return
        self._store.create_card(
            WorkCard(
                id=f"card-{uuid.uuid4().hex[:8]}",
                workflow_id=workflow.id,
                kind=CardKind.STRATEGIC_INTERVIEW.value,
                title="Strategic fit interview",
                state=CardState.READY,
                eligible_roles=("requester",),
            )
        )

    def _maybe_require_cab1_decision(self, resolved_gate: WorkCard) -> None:
        """Deterministically create the ``cab1_gate`` decision right after
        the requester's ``strategic_interview_gate`` answer is recorded.

        A no-op for any other gate kind — unconditional otherwise (once a
        ``strategic_interview_gate`` exists at all, CAB-1 is by
        construction already enabled; nothing else creates that kind).
        """
        if resolved_gate.kind != CardKind.STRATEGIC_INTERVIEW_GATE.value:
            return
        self.create_gate(
            resolved_gate.workflow_id,
            kind=CardKind.CAB1_GATE.value,
            title="Approve strategic fit",
            requested_decision="approve_strategic_fit",
        )

    def _maybe_require_refinement(self, resolved_gate: WorkCard) -> None:
        """Deterministically create the three persona interview cards
        right after refinement's trigger gate is approved, when enforced.

        The trigger is ``cab1_gate`` when CAB-1 is also required (feature
        027 — refinement must wait for a strategic go), else
        ``understanding_gate`` as before. A no-op for any other gate kind,
        when enforcement is off, or for a workflow whose source task is
        itself already a published decomposition child — a subtask
        Kestrel itself scoped out has already had its own refinement pass
        at the parent's level.
        """
        if (
            not self._required.prd
            or resolved_gate.kind != self._refinement_trigger_kind()
        ):
            return
        workflow = self._store.get_workflow(resolved_gate.workflow_id)
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

    #: Card kinds whose resolution may be the *last* thing a workflow's
    #: refinement phase was waiting on (feature 028: a persona can now
    #: finish via either an answered ``refinement_gate`` or a directly
    #: satisfied ``refinement`` card — see
    #: :meth:`mark_refinement_satisfied`).
    _REFINEMENT_COMPLETION_TRIGGERS = frozenset(
        {CardKind.REFINEMENT_GATE.value, CardKind.REFINEMENT.value}
    )

    def _maybe_start_prd(self, resolved_gate: WorkCard) -> None:
        """Create `pm`'s PRD-drafting card once every persona interview
        has reached a terminal state.

        A no-op for any other card kind, if any interview is still
        outstanding, or if a ``prd``/``prd_gate`` already exists (belt
        and suspenders — this should only ever become true once, at the
        moment the last interview resolves). A rejected interview counts
        as terminal too: the workflow must not deadlock on one persona
        never answering.
        """
        if resolved_gate.kind not in self._REFINEMENT_COMPLETION_TRIGGERS:
            return
        cards = self._store.list_cards(resolved_gate.workflow_id)
        if not has_any_round(cards) or still_pending(
            cards, self._gate_store.get_for_card, self._artifacts
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

    def _maybe_advance_refinement_round(self, resolved_gate: WorkCard) -> None:
        """Create the next interview round for one persona once their
        ``refinement_gate`` is answered, unless they're at the round cap
        (feature 028). Delegates to ``refinement_rounds.py`` (split out
        to stay within the repo's module-length limit).
        """
        maybe_advance_round(
            resolved_gate, self._store, self._gate_store.get_for_card,
            self._artifacts, self._required.refinement_round_cap,
        )

    def _maybe_approve_prd(self, prd_gate: WorkCard) -> None:
        """Record the approved PRD's content on the workflow, once its
        gate is approved. A no-op for any other gate kind."""
        content = self._approved_target(prd_gate, CardKind.PRD_GATE)
        if content is not None:
            self._store.record_approved_prd(prd_gate.workflow_id, content)

    def _maybe_materialise(self, gate: WorkCard) -> None:
        """Turn an approved CAB-2 decomposition into cards in the same
        workflow (feature 031) — never child tickets. A no-op for any
        other gate kind; see ``materialise.py``."""
        content = self._approved_target(gate, CardKind.DECOMPOSITION_GATE)
        if content is not None:
            materialise_decomposition(
                gate.workflow_id, content,
                MaterialiseTarget(self._store, self._artifacts),
            )

    def _approved_target(self, gate: WorkCard, kind: CardKind) -> str | None:
        """The content an approved *kind* gate targets, or ``None`` for
        another kind or a gate with no target (should not happen — both
        gate kinds are always created with one)."""
        if gate.kind != kind.value:
            return None
        record = self._gate_store.get_for_card(gate.id)
        if record is None or record.target_artifact_id is None:
            return None
        return self._artifacts.read_content(record.target_artifact_id)

    def _maybe_redraft_prd(self, prd_gate: WorkCard) -> None:
        """Route a ``prd_gate`` rejection to the coordinator for
        fix-vs-reinterview triage, capped so an unconvergeable PRD fails
        visibly instead of looping forever (feature 028).

        Delegates to ``prd_redraft.py`` (split out to stay within the
        repo's module-length limit) — a no-op there for any other gate
        kind.
        """
        maybe_redraft_prd(
            prd_gate, self._store, self._required.coordinator,
            self._required.prd_redraft_cap,
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
