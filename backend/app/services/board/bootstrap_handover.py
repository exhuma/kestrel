"""Composition root for watching work items' hand-over (#99).

Kept apart from ``bootstrap.py`` for its module-length budget; it builds
on the singletons there.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.persistence.board_store import get_board_store
from app.services.board.bootstrap import (
    get_board_service,
    get_coordinator_service,
    get_gates_service,
    get_projections_service,
    get_workspace_service,
)
from app.services.board.handback import HandbackDeps
from app.services.board.handover_poll import HandoverDeps, HandoverPollService
from app.services.task_sources import get_task_source_registry


@lru_cache
def get_handover_poll_service() -> HandoverPollService:
    """Return the process-wide HandoverPollService singleton."""
    return HandoverPollService(HandoverDeps(
        handback=HandbackDeps(
            store=get_board_store(),
            board=get_board_service(),
            projections=get_projections_service(),
            gates=get_gates_service(),
            workspace=get_workspace_service(),
        ),
        task_sources=get_task_source_registry(),
        coordinator=get_coordinator_service(),
        interval_seconds=get_settings().board_handover_poll_interval_seconds,
    ))
