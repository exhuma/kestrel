"""Delivery-card creation and push/PR dispatch (feature 026, T069).

Split out of ``dispatch_ready.py`` to keep that module under the repo's
500-line ceiling: this is the self-contained "push and open a change
request" concern, distinct from claiming and turning a specialist card.
``DispatchServices`` is imported only under ``TYPE_CHECKING`` — these
functions just read attributes off whatever they're given, so no runtime
import is needed, and importing one at module scope would cycle back to
``dispatch_ready.py`` (the only place ``DispatchServices`` is defined and
these functions are called from).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.documents import Document, Link, Text, document, paragraph
from app.models_board import CardKind, CardState, WorkCard, Workflow
from app.services.board.coordinator import (
    CreateCardAction,
    TransitionCardAction,
)
from app.services.board.delivery import deliver
from app.services.board.delivery_readiness import (
    delivery_due,
    delivery_trigger,
)
from app.services.board.write_back import ProjectionRequest, post_projection
from app.services.change_requests import change_request_number

if TYPE_CHECKING:
    from app.services.board.dispatch_ready import DispatchServices

_dispatch_log = logging.getLogger("kestrel.board.dispatch")


def _request_delivery(
    workflow_id: str, services: DispatchServices
) -> None:
    """Create the ``delivery`` card once a clean verification leaves the
    workflow's coding work settled (T069; feature 031, research R7).

    Never claimed by a specialist — ``_dispatch_pending_delivery`` below
    actually performs it, in this same dispatch pass or the next one a
    retry re-triggers. Keyed by the finished work it delivers, so one
    set of done implementation cards delivers exactly once.
    """
    store = services.claims.store
    cards = store.list_cards(workflow_id)
    if not delivery_due(cards, store.list_relations(workflow_id)):
        return
    trigger = delivery_trigger(cards)
    services.coordinator.apply_actions(
        workflow_id, trigger,
        [CreateCardAction(kind=CardKind.DELIVERY.value, title="Deliver")],
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


def _record_delivery(
    workflow: Workflow, location: str, services: DispatchServices
) -> None:
    """Record where delivery left the change request.

    A freshly opened one is identified by its URL. An update to the
    existing one reports only a note, so the recorded number and URL are
    kept rather than cleared (feature 043, FR-008).
    """
    number = change_request_number(location)
    if number is not None:
        url: str | None = location
    else:
        number = workflow.change_request_number
        url = workflow.change_request_url
    services.claims.store.record_delivery(workflow.id, number, url)


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
    _record_delivery(workflow, location, services)
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
                payload=_delivered(location),
            ),
            task_source,
            services.projections,
        )
    except Exception:  # noqa: BLE001 — never let projection crash dispatch
        _dispatch_log.exception(
            "workflow %s: delivery projection failed for card %s",
            workflow.id, card.id,
        )


def _delivered(location: str) -> Document:
    """Where the work was delivered: a link to the change request, or the
    local branch it was published to."""
    if location.startswith(("https://", "http://")):
        return document(paragraph(Text("Delivered: "), Link(location)))
    return document(paragraph(Text(f"Delivered: {location}")))
