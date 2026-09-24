"""Composition root for the board domain (feature 026).

Kept separate from ``services/workflows/bootstrap.py`` (the fixed
driver's composition root): the two coexist during this feature's
rollout, and board wiring does not yet need the old driver's task-source/
code-host ports — those are wired into board intake directly where the
protected-intake path calls into ingestion (see ``services/ingestion.py``).
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.persistence.board_quarantine_store import get_board_quarantine_store
from app.persistence.board_store import get_board_store
from app.policy import get_specialist_backend_policy
from app.services.board.quarantine import QuarantineService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster, load_roster
from app.storage.workflow_bus import get_workflow_bus


@lru_cache
def get_board_service() -> BoardService:
    """Return the process-wide BoardService singleton."""
    return BoardService(get_board_store(), get_workflow_bus())


@lru_cache
def get_specialist_roster() -> SpecialistRoster:
    """Return the process-wide, validated specialist roster.

    Loaded once and cached: a malformed or incomplete roster must fail
    startup rather than degrade silently mid-run (FR-009).
    """
    return load_roster(get_settings().specialists_root)


@lru_cache
def get_quarantine_service() -> QuarantineService:
    """Return the process-wide QuarantineService singleton."""
    settings = get_settings()
    return QuarantineService(
        get_board_quarantine_store(),
        get_specialist_roster(),
        get_specialist_backend_policy(),
        settings.board_input_max_bytes,
        settings.board_input_security_timeout_seconds,
    )
