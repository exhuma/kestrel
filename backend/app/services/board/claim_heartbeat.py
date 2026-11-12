"""Keep a running turn's card claimed for as long as the turn runs.

A claim lasts ``board_claim_lease_seconds`` unless renewed. While a turn
runs, this renews it every third of that, so a turn of any length keeps
its card, and the lease only decides how soon a card is recovered after
the kestrel process died mid-turn (``recovery.py``).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from app.models_board import WorkCard
from app.services.board.claims import ClaimsService

_log = logging.getLogger("kestrel.board.claims")


@asynccontextmanager
async def kept_claimed(
    claims: ClaimsService, card: WorkCard
) -> AsyncIterator[None]:
    """Renew *card*'s claim in the background while the block runs."""
    task = asyncio.create_task(_renew_until_cancelled(claims, card))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _renew_until_cancelled(claims: ClaimsService, card: WorkCard) -> None:
    interval = max(claims.default_lease_seconds / 3, 1.0)
    while True:
        await asyncio.sleep(interval)
        if not claims.renew(card):
            _log.warning(
                "card %s: its claim was lost while the turn ran", card.id,
                extra={"card_id": card.id},
            )
            return
        _log.debug("card %s: claim renewed", card.id)
