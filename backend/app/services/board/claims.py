"""Ready-card eligibility, atomic claims, and lifecycle (feature 026, T032).

Eligibility filtering and read-only capacity enforcement live here, above
the durable atomic-claim primitive in ``board_claims_store.py``: the store
guarantees a claim is safe once attempted, this service decides which
ready card a specialist may attempt to claim at all (FR-010, FR-011).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models_board import (
    ClaimRequest,
    CompleteOutcome,
    SpecialistDefinition,
    WorkCard,
    WorkspacePermission,
)
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board.specialists import SpecialistRoster


class NoEligibleCardError(Exception):
    """Raised when no ready card is currently eligible for this specialist."""


class ReadCapacityExceededError(Exception):
    """Raised when the process-wide read-only claim capacity is exhausted."""


@dataclass(frozen=True)
class ClaimsService:
    """Eligibility-checked claim/heartbeat/completion for board cards."""

    store: BoardStore
    claims_store: BoardClaimsStore
    roster: SpecialistRoster
    max_parallel_read_cards: int
    default_lease_seconds: float
    default_workspace_lease_seconds: float

    def claim_next_ready_card(
        self,
        workflow_id: str,
        specialist_id: str,
        *,
        backend_id: str | None = None,
    ) -> WorkCard:
        """Claim the first ready card this specialist is eligible for.

        :raises NoEligibleCardError: The specialist is unknown, or no
            ready card currently matches its role and capabilities, or
            the claim was lost to a concurrent claimant.
        :raises ReadCapacityExceededError: The card is read-only and the
            process-wide read-claim capacity is already full.
        """
        specialist = self.roster.get(specialist_id)
        if specialist is None:
            raise NoEligibleCardError(f"unknown specialist: {specialist_id}")
        card = self._first_eligible_card(workflow_id, specialist_id, specialist)
        if card is None:
            raise NoEligibleCardError(
                f"no ready card eligible for {specialist_id}"
            )
        is_write = card.workspace_permission == WorkspacePermission.WRITE.value
        if not is_write and self._read_capacity_exhausted():
            raise ReadCapacityExceededError(
                "read-only claim capacity exhausted"
            )
        request = self._request_for(card, specialist_id, backend_id)
        outcome = self.claims_store.claim_card(request)
        if not outcome.success:
            raise NoEligibleCardError(f"claim lost for card {card.id}")
        return self.store.get_card(card.id)

    def _first_eligible_card(
        self,
        workflow_id: str,
        specialist_id: str,
        specialist: SpecialistDefinition,
    ) -> WorkCard | None:
        return next(
            (
                card
                for card in self.store.list_cards(workflow_id)
                if _is_eligible(card, specialist_id, specialist)
            ),
            None,
        )

    def _read_capacity_exhausted(self) -> bool:
        return (
            self.claims_store.count_active_read_claims()
            >= self.max_parallel_read_cards
        )

    def _request_for(
        self, card: WorkCard, specialist_id: str, backend_id: str | None
    ) -> ClaimRequest:
        needs_repo = card.workspace_permission != WorkspacePermission.NONE.value
        workflow = self.store.get_workflow(card.workflow_id)
        repo = workflow.repo if needs_repo else None
        return ClaimRequest(
            card.id,
            specialist_id,
            self.default_lease_seconds,
            backend_id=backend_id,
            workspace_repo=repo,
            workspace_lease_seconds=self.default_workspace_lease_seconds,
        )

    def heartbeat(
        self, card_id: str, *, extend_seconds: float | None = None
    ) -> bool:
        """Extend an active claim's lease (see ``BoardClaimsStore``)."""
        return self.claims_store.heartbeat_claim(
            card_id,
            extend_seconds=extend_seconds or self.default_lease_seconds,
        )

    def complete(
        self,
        card_id: str,
        attempt_sequence: int,
        *,
        result: str,
        new_state: str,
    ) -> CompleteOutcome:
        """Complete an attempt (``BoardClaimsStore.complete_attempt``)."""
        return self.claims_store.complete_attempt(
            card_id, attempt_sequence, result=result, new_state=new_state
        )

    def expire_stale_leases(self) -> list[str]:
        """Recover every abandoned claim (see ``BoardClaimsStore``)."""
        return self.claims_store.expire_leases()


def _is_eligible(
    card: WorkCard, specialist_id: str, specialist: SpecialistDefinition
) -> bool:
    """Whether *specialist* may claim *card* right now."""
    return (
        card.state == "ready"
        and specialist_id in card.eligible_roles
        and card.kind in specialist.allowed_card_types
    )
