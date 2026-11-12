"""Composition root for the board domain (feature 026)."""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import Settings, get_settings
from app.documents import Document
from app.models_board import CardKind, WorkCard
from app.persistence.board_artifact_store import get_board_artifact_store
from app.persistence.board_claims_store import get_board_claims_store
from app.persistence.board_gate_store import get_board_gate_store
from app.persistence.board_projection_store import get_board_projection_store
from app.persistence.board_quarantine_store import get_board_quarantine_store
from app.persistence.board_store import get_board_store
from app.policy import get_specialist_backend_policy
from app.reasoning.client import ReasoningClient
from app.reasoning.policy import get_reasoning_policy
from app.services.board.announcements.content import GateContent
from app.services.board.announcements.service import (
    AnnouncementDeps,
    AnnouncementService,
)
from app.services.board.artifacts import ArtifactsService
from app.services.board.ci_poll import CiPollService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch import CardTurnError, SchedulingService
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.gates import GateRequirements, GatesService
from app.services.board.handover_poll import handover_supported
from app.services.board.interventions import InterventionsService
from app.services.board.live_activity import get_live_activity, turn_failure
from app.services.board.materialise import MaterialiseTarget
from app.services.board.projection_retry import ProjectionRetryService
from app.services.board.projections import ProjectionsService
from app.services.board.quarantine import QuarantineService
from app.services.board.recovery import RecoveryService
from app.services.board.requested_changes import RequestChangesService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster, load_roster
from app.services.board.turn_limits import TurnLimits
from app.services.board.work_items import WorkItemDeps, WorkItemPublisher
from app.services.board.workspace import WorkspaceService
from app.services.task_sources import get_task_source_registry
from app.storage.workflow_bus import get_workflow_bus

_logger = logging.getLogger(__name__)


@lru_cache
def get_board_service() -> BoardService:
    """Return the process-wide BoardService singleton."""
    return BoardService(
        get_board_store(), get_workflow_bus(), on_mutation=_on_mutation,
        on_gate_opened=_announce,
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
        get_reasoning_policy(),
        settings.board_input_max_bytes,
        get_reasoning_policy().timeout_for("input-security"),
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
        max_outage_retries=settings.board_backend_outage_retries,
    )


@lru_cache
def get_coordinator_service() -> CoordinatorService:
    """Return the process-wide CoordinatorService singleton."""
    return CoordinatorService(
        get_board_store(), get_board_service(),
        # Every gate is mandatory: CAB-1, PRD sign-off and CAB-2 (#70).
        decomposition_required=True,
        prd_gate_required=True,
    )


@lru_cache
def get_artifacts_service() -> ArtifactsService:
    """Return the process-wide ArtifactsService singleton."""
    return ArtifactsService(
        get_board_store(),
        get_board_artifact_store(),
        get_board_service(),
    )


@lru_cache
def get_gates_service() -> GatesService:
    """Return the process-wide GatesService singleton."""
    settings = get_settings()
    return GatesService(
        get_board_store(), get_board_gate_store(), get_board_service(),
        get_artifacts_service(),
        required=GateRequirements(
            # Mandatory in every deployment (#70): a request always
            # waits for CAB-1, PRD sign-off and CAB-2.
            decomposition=True,
            prd=True,
            cab1=True,
            cab1_interview_max_questions=(
                settings.board_cab1_interview_max_questions
            ),
            refinement_round_cap=settings.board_refinement_round_cap,
            prd_redraft_cap=settings.board_prd_redraft_cap,
            understanding_redraft_cap=(
                settings.board_understanding_redraft_cap
            ),
            coordinator=get_coordinator_service(),
            handover=lambda wid: handover_supported(
                get_board_store(), get_task_source_registry(), wid
            ),
        ),
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
def get_request_changes_service() -> RequestChangesService:
    """Return the process-wide RequestChangesService singleton."""
    return RequestChangesService(
        MaterialiseTarget(get_board_store(), get_artifacts_service()),
        get_board_service(),
        get_task_source_registry().code_hosts,
    )


@lru_cache
def get_projections_service() -> ProjectionsService:
    """Return the process-wide ProjectionsService singleton."""
    return ProjectionsService(get_board_projection_store())


def turn_limits(settings: Settings) -> TurnLimits:
    """How long an agent turn may run (``turn_limits``)."""
    return TurnLimits(
        settings.board_turn_idle_seconds, settings.board_turn_max_seconds
    )


@lru_cache
def get_work_item_publisher() -> WorkItemPublisher:
    """Return the process-wide WorkItemPublisher singleton (#64)."""
    return WorkItemPublisher(WorkItemDeps(
        store=get_board_store(),
        artifacts=get_artifacts_service(),
        projections=get_projections_service(),
        task_sources=get_task_source_registry(),
        announcements=get_announcement_service(),
        interval_seconds=get_settings().board_projection_retry_interval_seconds,
    ))


@lru_cache
def get_announcement_service() -> AnnouncementService:
    """Return the process-wide AnnouncementService singleton: what kestrel
    says on a request's ticket (feature 046)."""
    return AnnouncementService(
        AnnouncementDeps(
            store=get_board_store(),
            content=GateContent(
                get_board_store(), get_gates_service(),
                get_artifacts_service(), get_specialist_roster(),
            ),
            projections=get_projections_service(),
            task_sources=get_task_source_registry(),
            base_url=get_settings().public_base_url,
            marker=get_settings().feedback_marker,
        )
    )


@lru_cache
def get_projection_retry_service() -> ProjectionRetryService:
    """Return the process-wide ProjectionRetryService singleton."""
    return ProjectionRetryService(
        get_projections_service(),
        get_board_store(),
        get_task_source_registry(),
        interval_seconds=(
            get_settings().board_projection_retry_interval_seconds
        ),
    )


@lru_cache
def get_recovery_service() -> RecoveryService:
    """Return the process-wide RecoveryService singleton."""
    settings = get_settings()
    return RecoveryService(
        get_board_claims_store(),
        get_board_service(),
        interval_seconds=settings.board_recovery_interval_seconds,
        nudge=_trigger_scheduling,
    )


@lru_cache
def get_ci_poll_service() -> CiPollService:
    """Return the process-wide CiPollService singleton."""
    settings = get_settings()
    return CiPollService(
        get_board_store(),
        get_coordinator_service(),
        get_task_source_registry(),
        settings,
        announcements=get_announcement_service(),
    )


@lru_cache
def get_scheduling_service() -> SchedulingService:
    """Return the process-wide SchedulingService singleton."""
    settings = get_settings()
    return SchedulingService(
        get_board_store(),
        get_specialist_roster(),
        get_coordinator_service(),
        get_artifacts_service(),
        limits=turn_limits(settings),
    )


@lru_cache
def get_workspace_service() -> WorkspaceService:
    """Return the process-wide board WorkspaceService singleton."""
    return WorkspaceService(get_settings().workspace_root)


@lru_cache
def get_dispatch_services() -> DispatchServices:
    """Return the process-wide DispatchServices bundle."""
    return DispatchServices(
        get_claims_service(),
        get_specialist_roster(),
        get_artifacts_service(),
        workspace=get_workspace_service(),
        task_sources=get_task_source_registry(),
        coordinator=get_coordinator_service(),
        announcements=get_announcement_service(),
        gates=get_gates_service(),
        verify_round_cap=get_settings().max_verify_iterations,
        board=get_board_service(),
        live=get_live_activity(),
        unreadable_retry_cap=get_settings().board_unreadable_retry_cap,
        reasoning=get_reasoning_policy(),
    )


def _announce(workflow_id: str) -> None:
    """Have the ticket told whatever is new on *workflow_id* (feature
    046). Fire-and-forget: the service logs its own failures."""
    get_announcement_service().schedule(workflow_id)


def _on_mutation(workflow_id: str) -> None:
    """``BoardService``'s ``on_mutation`` hook: wake the coordinator and
    let the ticket know."""
    _trigger_scheduling(workflow_id)
    _announce(workflow_id)


def _trigger_scheduling(workflow_id: str) -> None:
    """Wake the coordinator, then try dispatching ready work (FR-004).

    ``BoardService``'s ``on_mutation`` hook: fired synchronously from
    inside a committed mutation, so it only schedules the (async, LLM-
    calling) wake-up rather than awaiting it — mirrors
    ``WorkflowService._spawn_driver``'s background-task pattern.
    """
    coordinator = get_specialist_roster().get("coordinator")
    backend = get_reasoning_policy().backend_for(coordinator)
    task = asyncio.create_task(_wake_and_dispatch(workflow_id, backend))
    task.add_done_callback(
        lambda t, wid=workflow_id: _log_scheduling_exception(t, wid)
    )


async def _wake_and_dispatch(
    workflow_id: str, coordinator_backend: ReasoningClient
) -> None:
    """One coordinator turn, then one best-effort dispatch pass per role.

    Sequential, not concurrent: the coordinator's own proposed cards
    (create_card/transition_card) should exist before specialists are
    tried against this same trigger, though a specialist claim is safe
    either way (atomic, per-card).
    """
    try:
        with get_live_activity().track(workflow_id, "coordinator"):
            await get_scheduling_service().wake(
                workflow_id, coordinator_backend
            )
    except CardTurnError as exc:
        # A failed or timed-out coordinator turn must not strand the
        # board: ready cards still get dispatched (#69), and the request
        # says what went wrong (feature 033).
        _logger.warning(
            "workflow %s: coordinator turn failed; dispatching anyway",
            workflow_id, exc_info=True,
        )
        get_board_service().record_problem(
            workflow_id, event_type="coordinator.turn_failed",
            detail=turn_failure("the coordinator", exc),
        )
    settings = get_settings()
    await dispatch_ready_work(
        workflow_id,
        get_dispatch_services(),
        get_specialist_backend_policy().backend_for,
        limits=turn_limits(settings),
    )


def _log_scheduling_exception(task: asyncio.Task, workflow_id: str) -> None:
    """Log a coordinator wake-up/dispatch pass's terminal exception, if any.

    Without this, a failed background task dies with its exception
    unretrieved (asyncio only logs a generic, easy-to-miss warning).
    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _logger.error(
            "workflow %s: scheduling/dispatch failed", workflow_id,
            exc_info=exc,
        )


def schedule_gate_projection(
    workflow_id: str, card: WorkCard, decision: str
) -> None:
    """Schedule posting a resolved gate's decision to its task source
    (feature 026, T067), in the background.

    Mirrors ``_trigger_scheduling``'s own fire-and-forget pattern: the
    caller (a router handler) must not block its HTTP response on a
    task-source round trip.
    """
    task = asyncio.create_task(_project_gate(workflow_id, card, decision))
    task.add_done_callback(
        lambda t, wid=workflow_id: _log_scheduling_exception(t, wid)
    )


async def _project_gate(
    workflow_id: str, card: WorkCard, decision: str
) -> None:
    await get_announcement_service().gate_decided(workflow_id, card, decision)


def schedule_gate_followup(
    workflow_id: str, card: WorkCard, decision: str
) -> None:
    """Schedule a resolved gate's kind-specific follow-up, if it has one
    (the breakdown's work items; the approved PRD or understanding as a
    file), however it was decided."""
    if decision != "approved":
        return
    if card.kind == CardKind.DECOMPOSITION_GATE.value:
        schedule_breakdown_projection(workflow_id, card)
    elif card.kind in _ATTACHED:
        schedule_attachment_projection(workflow_id, card)


def schedule_escalation_projection(workflow_id: str, card: WorkCard) -> None:
    """Schedule posting an operator-requested coordinator review to its
    task source (feature 026, T067), in the background.

    The verifier-routed escalation path (T051,
    ``dispatch_ready.py::_project_escalation``) posts its own; this is
    the other place a ``coordinator_review`` card is created.
    """
    task = asyncio.create_task(_project_escalation(workflow_id, card))
    task.add_done_callback(
        lambda t, wid=workflow_id: _log_scheduling_exception(t, wid)
    )


async def _project_escalation(workflow_id: str, card: WorkCard) -> None:
    await get_announcement_service().escalated(
        workflow_id, f"escalation:{card.id}", card.title
    )


def schedule_breakdown_projection(workflow_id: str, _card: WorkCard) -> None:
    """Have an approved breakdown's tasks created as work items on the
    task source, and listed in one comment (#64), in the background. The
    publisher's own loop finishes whatever this pass cannot."""
    get_work_item_publisher().schedule(workflow_id)


def schedule_attachment_projection(workflow_id: str, card: WorkCard) -> None:
    """Schedule attaching an approved gate's document (the PRD, the
    understanding) to the ticket, in the background."""
    task = asyncio.create_task(_project_attachment(workflow_id, card))
    task.add_done_callback(
        lambda t, wid=workflow_id: _log_scheduling_exception(t, wid)
    )


#: Gates whose approved document goes on the ticket as a file: the
#: file's stem, and how to read the approved document.
_ATTACHED = {
    CardKind.UNDERSTANDING_GATE.value: "Understanding",
    CardKind.PRD_GATE.value: "PRD",
}


async def _project_attachment(workflow_id: str, card: WorkCard) -> None:
    """Attach an approved gate's document (the PRD, the understanding) to
    the ticket as a file. The decision's own comment says so."""
    approved = _approved_document(workflow_id, card)
    if approved is None:
        _logger.warning(
            "workflow %s: %s %s approved but its document is not recorded; "
            "nothing attached", workflow_id, card.kind, card.id,
        )
        return
    name = _attachment_name(workflow_id, card.kind)
    await get_announcement_service().attach(
        workflow_id, f"attachment:{card.id}:{name}", approved
    )


def _approved_document(workflow_id: str, card: WorkCard) -> Document | None:
    if card.kind == CardKind.PRD_GATE.value:
        workflow = get_board_store().get_workflow(workflow_id)
        return workflow.approved_prd if workflow is not None else None
    gate = get_gates_service().get_gate(card.id)
    if gate is None or gate.target_artifact_id is None:
        return None
    return get_artifacts_service().read_document(gate.target_artifact_id)


def _attachment_name(workflow_id: str, kind: str) -> str:
    """``PRD.md`` / ``Understanding.md`` for the first approval of *kind*,
    ``PRD-2.md`` and so on for one approved again after a change."""
    approved = sum(
        1 for c in get_board_store().list_cards(workflow_id)
        if c.kind == kind and c.state == "done"
    )
    stem = _ATTACHED[kind]
    return f"{stem}.md" if approved <= 1 else f"{stem}-{approved}.md"
