"""Startup and periodic claim-expiry recovery (feature 026, FR-004, FR-012).

``BoardClaimsStore.expire_leases`` already durably resolves each abandoned
claim to its next state (``ready`` for retry/reassignment, within
``attempt_limit``, or the terminal ``failed`` once exhausted — escalation).
That bulk sweep bypasses ``BoardService.transition_card`` (it enforces its
own two valid destinations directly, in one transaction, across every
expired card at once), so this service's job is only to make each
recovered card's outcome visible the same way any other mutation is: an
event, a bumped revision, and a coordinator wake-up.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

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
    ) -> None:
        self._claims_store = claims_store
        self._board_service = board_service
        self._interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        """Sweep for expired claims until cancelled."""
        while True:
            self.recover_expired_claims()
            await asyncio.sleep(self._interval_seconds)

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
