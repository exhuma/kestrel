"""Composition root for the board domain (feature 026).

Kept separate from ``services/workflows/bootstrap.py`` (the fixed
driver's composition root): the two coexist during this feature's
rollout, and board wiring does not yet need the old driver's task-source/
code-host ports — those are wired into board intake directly where the
protected-intake path calls into ingestion (see ``services/ingestion.py``).
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import get_settings
from app.persistence.board_artifact_content_store import (
    get_board_artifact_content_store,
)
from app.persistence.board_artifact_store import get_board_artifact_store
from app.persistence.board_claims_store import get_board_claims_store
from app.persistence.board_coordinator_store import get_board_coordinator_store
from app.persistence.board_gate_store import get_board_gate_store
from app.persistence.board_projection_store import get_board_projection_store
from app.persistence.board_quarantine_store import get_board_quarantine_store
from app.persistence.board_store import get_board_store
from app.policy import get_specialist_backend_policy
from app.services.board.artifacts import ArtifactsService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch import SchedulingService
from app.services.board.gates import GatesService
from app.services.board.interventions import InterventionsService
from app.services.board.projections import ProjectionsService
from app.services.board.quarantine import QuarantineService
from app.services.board.recovery import RecoveryService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster, load_roster
from app.storage.workflow_bus import get_workflow_bus

_logger = logging.getLogger(__name__)


@lru_cache
def get_board_service() -> BoardService:
    """Return the process-wide BoardService singleton."""
    return BoardService(
        get_board_store(), get_workflow_bus(), on_mutation=_trigger_scheduling
    )


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


@lru_cache
def get_claims_service() -> ClaimsService:
    """Return the process-wide ClaimsService singleton."""
    settings = get_settings()
    return ClaimsService(
        store=get_board_store(),
        claims_store=get_board_claims_store(),
        roster=get_specialist_roster(),
        max_parallel_read_cards=settings.board_max_parallel_read_cards,
        default_lease_seconds=settings.board_claim_lease_seconds,
        default_workspace_lease_seconds=settings.board_workspace_lease_seconds,
    )


@lru_cache
def get_coordinator_service() -> CoordinatorService:
    """Return the process-wide CoordinatorService singleton."""
    return CoordinatorService(
        get_board_store(), get_board_coordinator_store(), get_board_service()
    )


@lru_cache
def get_artifacts_service() -> ArtifactsService:
    """Return the process-wide ArtifactsService singleton."""
    return ArtifactsService(
        get_board_store(),
        get_board_artifact_store(),
        get_board_service(),
        get_board_artifact_content_store(),
    )


@lru_cache
def get_gates_service() -> GatesService:
    """Return the process-wide GatesService singleton."""
    return GatesService(
        get_board_store(), get_board_gate_store(), get_board_service()
    )


@lru_cache
def get_interventions_service() -> InterventionsService:
    """Return the process-wide InterventionsService singleton."""
    return InterventionsService(
        get_board_store(),
        get_board_claims_store(),
        get_board_service(),
        get_gates_service(),
    )


@lru_cache
def get_projections_service() -> ProjectionsService:
    """Return the process-wide ProjectionsService singleton."""
    return ProjectionsService(get_board_projection_store())


@lru_cache
def get_recovery_service() -> RecoveryService:
    """Return the process-wide RecoveryService singleton."""
    settings = get_settings()
    return RecoveryService(
        get_board_claims_store(),
        get_board_service(),
        interval_seconds=settings.board_recovery_interval_seconds,
    )


@lru_cache
def get_scheduling_service() -> SchedulingService:
    """Return the process-wide SchedulingService singleton."""
    settings = get_settings()
    return SchedulingService(
        get_board_store(),
        get_specialist_roster(),
        get_coordinator_service(),
        default_timeout_seconds=settings.board_input_security_timeout_seconds,
    )


def _trigger_scheduling(workflow_id: str) -> None:
    """Wake the coordinator for *workflow_id* in the background (FR-004).

    ``BoardService``'s ``on_mutation`` hook: fired synchronously from
    inside a committed mutation, so it only schedules the (async, LLM-
    calling) wake-up rather than awaiting it — mirrors
    ``WorkflowService._spawn_driver``'s background-task pattern.
    """
    coordinator = get_specialist_roster().get("coordinator")
    backend = get_specialist_backend_policy().backend_for(coordinator)
    task = asyncio.create_task(
        get_scheduling_service().wake(workflow_id, backend)
    )
    task.add_done_callback(
        lambda t, wid=workflow_id: _log_scheduling_exception(t, wid)
    )


def _log_scheduling_exception(task: asyncio.Task, workflow_id: str) -> None:
    """Log a coordinator wake-up's terminal exception, if any.

    Without this, a failed background wake dies with its exception
    unretrieved (asyncio only logs a generic, easy-to-miss warning).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(
            "workflow %s: coordinator wake-up failed", workflow_id,
            exc_info=exc,
        )
