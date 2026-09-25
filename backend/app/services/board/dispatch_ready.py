"""The automatic ready-card dispatch loop (feature 026, T034/T041/T051).

Split out of ``dispatch.py`` to keep that module under the repo's
500-line ceiling: this is the "later phase's concern" its own docstring
deferred — turning the claim/turn primitives defined there into an
actual event-driven loop tried once per non-coordinator role on every
board mutation (see ``bootstrap.py::_trigger_scheduling``).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from app.models_board import (
    CardKind,
    CardState,
    SpecialistDefinition,
    WorkCard,
    Workflow,
    WorkspacePermission,
)
from app.policy import SpecialistCapabilityError
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.claims import (
    ClaimsService,
    NoEligibleCardError,
    ReadCapacityExceededError,
)
from app.services.board.coordinator import (
    CoordinatorService,
    CreateCardAction,
    TransitionCardAction,
)
from app.services.board.decomposition import route_decomposition_result
from app.services.board.delivery import deliver
from app.services.board.dispatch import (
    CardTurnError,
    _TurnBackend,
    build_card_envelope,
    run_card_turn,
)
from app.services.board.gates import GatesService
from app.services.board.projections import ProjectionsService
from app.services.board.refinement import (
    gather_refinement_context,
    route_prd_result,
    route_refinement_result,
)
from app.services.board.specialists import SpecialistRoster
from app.services.board.verification import route_verifier_result
from app.services.board.workspace import WorkspaceRequest, WorkspaceService
from app.services.board.write_back import ProjectionRequest, post_projection
from app.services.exceptions import GitError
from app.services.github import change_request_number
from app.services.task_sources import TaskSourceRegistry

_dispatch_log = logging.getLogger("kestrel.board.dispatch")


@dataclass(frozen=True)
class DispatchServices:
    """The board collaborators :func:`dispatch_ready_work` claims/reports
    through. Bundled to keep that function's argument count within the
    repo's limit.

    :param workspace: Provisions a real git worktree for a ``read_only``/
        ``write`` card. ``None`` keeps every turn at ``cwd=""`` (the
        pre-T041 behavior) — e.g. for a deployment with no configured
        task sources to resolve a code host from.
    :param task_sources: Resolves a workflow's ``CodeHost`` (for the clone
        remote/credential a workspace is provisioned from) and, for
        escalation projection, its ``TaskSource`` — both by ``source``.
    :param coordinator: Routes a completed ``verification`` card's parsed
        findings into new remediation/escalation cards (T051). ``None``
        leaves a verification card's result generically accepted like any
        other card's, with no follow-up card created.
    :param projections: Posts a routed escalation finding to its task
        source (T067). ``None`` skips projection — the escalation card
        is still created either way.
    :param gates: Holds a parsed decomposition candidate behind a
        ``decomposition_gate`` card (T068). ``None`` leaves a
        ``decomposition`` card's result generically accepted with no
        gate created — effectively disabling decomposition.
    """

    claims: ClaimsService
    roster: SpecialistRoster
    artifacts: ArtifactsService
    workspace: WorkspaceService | None = None
    task_sources: TaskSourceRegistry | None = None
    coordinator: CoordinatorService | None = None
    projections: ProjectionsService | None = None
    gates: GatesService | None = None


async def dispatch_ready_work(
    workflow_id: str,
    services: DispatchServices,
    backend_for: Callable[[SpecialistDefinition], _TurnBackend],
    *,
    timeout_seconds: float,
) -> None:
    """Try one claim-and-turn cycle per non-coordinator role (FR-004).

    Best-effort per specialist: a capability mismatch, absent eligible
    work, or a turn failure for one role must never stop the others from
    being tried. A card left claimed after a failed/timed-out turn is
    recovered by the periodic lease-expiry sweep (``recovery.py``), not
    retried here.

    A ``read_only``/``write`` card gets a real, git-backed ``cwd``
    (T041's ``WorkspaceService``) when ``services.workspace`` is
    configured; a ``write`` card additionally runs with
    ``permission_mode="acceptEdits"`` so a ``FILE_EDITS`` specialist can
    actually edit. After every role has been tried, one pass also
    attempts any ``ready`` ``delivery`` card (T069) — pushing a cleanly
    verified workflow's branch and opening its change request is a
    system action, not a specialist turn, so it isn't claimed like the
    roles above.
    """
    for specialist_id in sorted(services.roster.ids() - {"coordinator"}):
        specialist = services.roster.get(specialist_id)
        if specialist is None:
            continue
        await _dispatch_one(
            workflow_id, services, specialist, backend_for,
            timeout_seconds=timeout_seconds,
        )
    await _dispatch_pending_delivery(workflow_id, services)


def _claim_for(
    workflow_id: str,
    services: DispatchServices,
    specialist: SpecialistDefinition,
    backend_for: Callable[[SpecialistDefinition], _TurnBackend],
) -> tuple[_TurnBackend, WorkCard] | None:
    """Resolve a backend and claim this specialist's next ready card.

    :returns: ``None`` if the backend can't serve this role, there is no
        eligible ready work, or read-only claim capacity is exhausted —
        every case a no-op for this dispatch cycle, not an error.
    """
    try:
        backend = backend_for(specialist)
    except SpecialistCapabilityError:
        _dispatch_log.warning(
            "workflow %s: specialist %s has no capable backend",
            workflow_id, specialist.id,
        )
        return None
    try:
        card = services.claims.claim_next_ready_card(
            workflow_id, specialist.id, backend_id=getattr(backend, "id", None)
        )
    except NoEligibleCardError:
        return None
    except ReadCapacityExceededError as exc:
        _dispatch_log.warning(
            "workflow %s: %s dispatch skipped: %s",
            workflow_id, specialist.id, exc,
        )
        return None
    return backend, card


async def _dispatch_one(
    workflow_id: str,
    services: DispatchServices,
    specialist: SpecialistDefinition,
    backend_for: Callable[[SpecialistDefinition], _TurnBackend],
    *,
    timeout_seconds: float,
) -> None:
    """Claim, turn, and accept one card's result for one specialist."""
    claimed = _claim_for(workflow_id, services, specialist, backend_for)
    if claimed is None:
        return
    backend, card = claimed
    workspace = await _resolve_workspace(workflow_id, card, services)
    if workspace is None:
        return
    cwd, permission_mode = workspace
    workflow = services.claims.store.get_workflow(workflow_id)
    extra_context = (
        gather_refinement_context(
            workflow_id, services.claims.store, services.artifacts
        )
        if card.kind == CardKind.PRD.value
        else ""
    )
    envelope = build_card_envelope(
        specialist, workflow, card, extra_context=extra_context
    )
    try:
        result = await run_card_turn(
            backend, envelope, cwd=cwd, timeout_seconds=timeout_seconds,
            permission_mode=permission_mode,
        )
    except CardTurnError as exc:
        _dispatch_log.warning(
            "workflow %s: %s's turn on card %s failed: %s",
            workflow_id, specialist.id, card.id, exc,
        )
        return
    outcome = services.claims.complete(
        card.id, card.attempt_count,
        result=result.final_text, new_state="review",
    )
    if not outcome.success:
        _dispatch_log.warning(
            "workflow %s: %s's claim on card %s went stale before it "
            "could complete (%s) — leaving it for recovery",
            workflow_id, specialist.id, card.id, outcome.reason,
        )
        return
    services.artifacts.submit_result(
        ArtifactDraft(
            producer_card_id=card.id,
            logical_name="report",
            revision=card.attempt_count,
            content=result.final_text,
            trust="agent_output",
        )
    )
    await _route_result(workflow_id, card, result.final_text, services)


async def _route_result(
    workflow_id: str,
    card: WorkCard,
    final_text: str,
    services: DispatchServices,
) -> None:
    """Route one accepted card's result, by kind, to its follow-up card
    creation — extracted from ``_dispatch_one`` to keep it within the
    repo's branch-count limit."""
    if card.kind == CardKind.VERIFICATION.value and services.coordinator:
        await _route_verification(workflow_id, card, final_text, services)
    elif (
        card.kind == CardKind.DECOMPOSITION.value
        and services.coordinator
        and services.gates
    ):
        route_decomposition_result(
            final_text, card, services.coordinator, services.gates,
            services.artifacts,
        )
    elif (
        card.kind == CardKind.REFINEMENT.value
        and services.coordinator
        and services.gates
    ):
        route_refinement_result(
            final_text, card, services.coordinator, services.gates,
            services.artifacts,
        )
    elif (
        card.kind == CardKind.PRD.value
        and services.coordinator
        and services.gates
    ):
        route_prd_result(
            final_text, card, services.coordinator, services.gates,
            services.artifacts,
        )


async def _route_verification(
    workflow_id: str,
    card: WorkCard,
    final_text: str,
    services: DispatchServices,
) -> None:
    """Best-effort: a routing failure must not undo the already-accepted
    verification card result above it."""
    try:
        routing = route_verifier_result(final_text, card, services.coordinator)
    except Exception:  # noqa: BLE001 — never let routing crash dispatch
        _dispatch_log.exception(
            "workflow %s: verifier-finding routing failed for card %s",
            workflow_id, card.id,
        )
        return
    for index, summary in enumerate(routing.escalations):
        await _project_escalation(workflow_id, card, index, summary, services)
    if routing.clean:
        _request_delivery(workflow_id, card, services)


def _request_delivery(
    workflow_id: str, card: WorkCard, services: DispatchServices
) -> None:
    """Create the ``delivery`` card for a cleanly verified workflow
    (T069). Never claimed by a specialist — ``_dispatch_pending_delivery``
    below actually performs it, in this same dispatch pass or the next
    one a retry re-triggers.
    """
    trigger = f"delivery:{card.id}:{card.attempt_count}"
    services.coordinator.apply_actions(
        workflow_id, trigger,
        [CreateCardAction(kind=CardKind.DELIVERY.value, title="Deliver")],
    )


async def _project_escalation(
    workflow_id: str,
    card: WorkCard,
    index: int,
    summary: str,
    services: DispatchServices,
) -> None:
    """Best-effort projection of one escalation finding (T067)."""
    if services.projections is None or services.task_sources is None:
        return
    workflow = services.claims.store.get_workflow(workflow_id)
    task_source = services.task_sources.sources.get(workflow.source)
    if task_source is None:
        return
    try:
        await post_projection(
            ProjectionRequest(
                workflow_id=workflow_id,
                task_ref=workflow.task_ref,
                kind="escalation",
                idempotency_key=(
                    f"escalation:{card.id}:{card.attempt_count}:{index}"
                ),
                payload=f"Escalation: {summary}",
            ),
            task_source,
            services.projections,
        )
    except Exception:  # noqa: BLE001 — never let projection crash dispatch
        _dispatch_log.exception(
            "workflow %s: escalation projection failed for card %s",
            workflow_id, card.id,
        )


async def _dispatch_pending_delivery(
    workflow_id: str, services: DispatchServices
) -> None:
    """Attempt every ``ready`` ``delivery`` card in this workflow (T069).

    Runs on the same pass a clean verification created one (right after
    the per-role loop above, in the same ``dispatch_ready_work`` call),
    and on any later pass an operator's ``retry`` intervention re-opens
    one on — a card transition is a board mutation like any other, so it
    re-triggers dispatch the normal way.
    """
    if services.workspace is None or services.task_sources is None:
        return
    for card in services.claims.store.list_cards(workflow_id):
        if (
            card.kind == CardKind.DELIVERY.value
            and card.state == CardState.READY.value
        ):
            await _deliver_one(workflow_id, card, services)


async def _deliver_one(
    workflow_id: str, card: WorkCard, services: DispatchServices
) -> None:
    """Push and open a change request for one ``delivery`` card.

    Moves through ``claimed``/``review``/``done`` like a specialist-
    worked card, for a consistent state machine and so a failure leaves
    it ``failed`` (retry-able via the ordinary ``retry`` intervention) —
    but this is not a real claim/lease (no specialist backend, nothing
    for ``recovery.py``'s lease-expiry sweep to see), so a process crash
    between the claim transition and delivery completing leaves the card
    stuck ``claimed``; an operator must cancel it and retry the
    verification card that requested it. Accepted as a narrow, rare
    window rather than building lease-based recovery for a system action.
    """
    workflow = services.claims.store.get_workflow(workflow_id)
    code_host = services.task_sources.code_hosts.get(workflow.source)
    if code_host is None:
        _dispatch_log.warning(
            "workflow %s: no code host for source %r; delivery not "
            "attempted", workflow_id, workflow.source,
        )
        return
    services.coordinator.apply_actions(
        workflow_id, f"delivery:{card.id}:claim",
        [TransitionCardAction(card.id, CardState.CLAIMED.value)],
    )
    try:
        location = await deliver(workflow, code_host, services.workspace)
    except Exception:  # noqa: BLE001 — record failure, never crash dispatch
        _dispatch_log.exception(
            "workflow %s: delivery failed for card %s", workflow_id, card.id,
        )
        services.coordinator.apply_actions(
            workflow_id, f"delivery:{card.id}:fail",
            [TransitionCardAction(card.id, CardState.FAILED.value)],
        )
        return
    services.claims.store.record_delivery(
        workflow_id, change_request_number(location)
    )
    services.coordinator.apply_actions(
        workflow_id, f"delivery:{card.id}:review",
        [TransitionCardAction(card.id, CardState.REVIEW.value)],
    )
    services.coordinator.apply_actions(
        workflow_id, f"delivery:{card.id}:done",
        [TransitionCardAction(card.id, CardState.DONE.value)],
    )
    await _project_delivery(workflow, card, location, services)


async def _project_delivery(
    workflow: Workflow,
    card: WorkCard,
    location: str,
    services: DispatchServices,
) -> None:
    """Best-effort projection of a workflow's delivery location (T067)."""
    if services.projections is None or services.task_sources is None:
        return
    task_source = services.task_sources.sources.get(workflow.source)
    if task_source is None:
        return
    try:
        await post_projection(
            ProjectionRequest(
                workflow_id=workflow.id,
                task_ref=workflow.task_ref,
                kind="delivery",
                idempotency_key=f"delivery:{card.id}",
                payload=f"Delivered: {location}",
            ),
            task_source,
            services.projections,
        )
    except Exception:  # noqa: BLE001 — never let projection crash dispatch
        _dispatch_log.exception(
            "workflow %s: delivery projection failed for card %s",
            workflow.id, card.id,
        )


async def _resolve_workspace(
    workflow_id: str, card: WorkCard, services: DispatchServices
) -> tuple[str, str] | None:
    """Resolve a card's ``(cwd, permission_mode)``, provisioning a real
    workspace for ``read_only``/``write`` cards.

    :returns: ``("", "plan")`` for a ``none``-permission card, or once a
        real workspace is configured and provisioned; ``None`` if a
        ``read_only``/``write`` card needed one but couldn't get one —
        the caller must then leave the card claimed for recovery rather
        than dispatch a specialist that would silently lack the repo
        access its result implicitly claims.
    """
    if card.workspace_permission == WorkspacePermission.NONE.value:
        return "", "plan"
    if services.workspace is None or services.task_sources is None:
        _dispatch_log.warning(
            "workflow %s: card %s needs a workspace but none is "
            "configured", workflow_id, card.id,
        )
        return None
    workflow = services.claims.store.get_workflow(workflow_id)
    code_host = services.task_sources.code_hosts.get(workflow.source)
    if code_host is None:
        _dispatch_log.warning(
            "workflow %s: no code host for source %r", workflow_id,
            workflow.source,
        )
        return None
    request = WorkspaceRequest(
        code_host.clone_remote(workflow.repo), workflow.repo,
        workflow.base_branch, workflow_id, code_host.git_credential(),
    )
    try:
        cwd = await services.workspace.ensure_workspace(request)
    except GitError as exc:
        _dispatch_log.warning(
            "workflow %s: workspace provisioning failed: %s",
            workflow_id, exc,
        )
        return None
    # A verification card is read_only (it must never edit files/commit)
    # but still needs to run tests/checks via tool execution, which "plan"
    # (proposal-only) mode does not reliably support headlessly — so it
    # gets the same execution-capable mode a write card does.
    needs_execution = (
        card.workspace_permission == WorkspacePermission.WRITE.value
        or card.kind == CardKind.VERIFICATION.value
    )
    return cwd, ("acceptEdits" if needs_execution else "plan")
