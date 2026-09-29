"""Startup and periodic claim-expiry recovery (feature 026, FR-004, FR-012).

``BoardClaimsStore.expire_leases`` already durably resolves each abandoned
claim to its next state (``ready`` for retry/reassignment, within
``attempt_limit``, or the terminal ``failed`` once exhausted — escalation).
That bulk sweep bypasses ``BoardService.transition_card`` (it enforces its
own two valid destinations directly, in one transaction, across every
expired card at once), so this service's job is only to make each
recovered card's outcome visible the same way any other mutation is: an
event, a bumped revision, and a coordinator wake-up.

The same sweep also nudges any workflow whose ready work nobody is
working on (#69). Dispatch is otherwise only triggered by a board
mutation, so one failed pass — a coordinator turn timing out, say —
would leave a ready card waiting for ever.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from app.models_board import CardState, WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.services.board.service import BoardService

_RETRIED_EVENT = "card.recovery_retry"
_ESCALATED_EVENT = "card.recovery_escalated"


class RecoveryService:
    """Sweeps expired claim leases and records their recovery outcome."""

    def __init__(
        self,
        claims_store: BoardClaimsStore,
        board_service: BoardService,
        *,
        interval_seconds: float,
        nudge: Callable[[str], None] | None = None,
    ) -> None:
        """
        :param nudge: Re-triggers scheduling for one workflow (the same
            hook a board mutation fires); ``None`` disables nudging.
        """
        self._claims_store = claims_store
        self._board_service = board_service
        self._interval_seconds = interval_seconds
        self._nudge = nudge

    async def run_forever(self) -> None:
        """Sweep for expired claims until cancelled."""
        while True:
            self.recover_expired_claims()
            self.nudge_waiting_work()
            await asyncio.sleep(self._interval_seconds)

    def nudge_waiting_work(self) -> list[str]:
        """Re-trigger scheduling for every workflow with claimable ready
        work and nothing in progress.

        Cheap when nothing can move: the coordinator skips a revision it
        already woke for, and a claim that finds no capable specialist
        costs no model call.

        :returns: The ids of the workflows nudged.
        """
        if self._nudge is None:
            return []
        nudged = [
            w.id for w in self._board_service.list_workflows()
            if _waiting(self._board_service.list_cards(w.id))
        ]
        for workflow_id in nudged:
            self._nudge(workflow_id)
        return nudged

    def recover_expired_claims(
        self, *, now: datetime | None = None
    ) -> list[str]:
        """Resolve every currently-expired claim and record its outcome.

        :returns: The ids of cards recovered this sweep.
        """
        expired = self._claims_store.expire_leases(now=now)
        for card_id in expired:
            self._record_outcome(card_id)
        return expired

    def _record_outcome(self, card_id: str) -> None:
        card = self._board_service.get_card(card_id)
        if card is None:
            return
        event_type = (
            _ESCALATED_EVENT if card.state == "failed" else _RETRIED_EVENT
        )
        self._board_service.record_recovery_event(card_id, event_type)


def _waiting(cards: list[WorkCard]) -> bool:
    """Ready work a specialist could take, and no claim in progress."""
    if any(c.state == CardState.CLAIMED.value for c in cards):
        return False
    return any(
        c.state == CardState.READY.value and c.eligible_roles for c in cards
    )
