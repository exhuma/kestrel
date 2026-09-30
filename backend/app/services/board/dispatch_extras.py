"""Per-card-kind extras for a card turn: what its envelope adds, and where
its accepted result goes next.

Split out of ``dispatch_ready.py`` to keep it within the module size
limit (feature 038 added the interview's plan and review cards).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from app.models_board import CardKind, WorkCard
from app.models_board_records import BoardEventRecord
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.coordinator import CreateCardAction
from app.services.board.decomposition import (
    RoutingServices,
    route_decomposition_result,
)
from app.services.board.estimation import (
    estimation_context,
    route_estimation_result,
)
from app.services.board.interview_plan import (
    InterviewServices,
    plan_context,
    route_plan_result,
)
from app.services.board.materialise import task_context
from app.services.board.question_review import (
    after_draft,
    answered_elsewhere,
    review_context,
    route_review_result,
)
from app.services.board.questions import INTERVIEWER_BRIEF, QUESTION_FORMAT
from app.services.board.refinement import (
    gather_refinement_context,
    route_prd_result,
    route_refinement_result,
    route_strategic_interview_result,
)
from app.services.board.refinement_rounds import round_context
from app.services.board.retries import (
    AUTOMATIC,
    UnreadableResultError,
    detail_of,
    retries_of,
    retry_card,
    retry_context,
)
from app.services.board.understanding import (
    route_understanding_result,
    understanding_context,
)

if TYPE_CHECKING:
    from app.services.board.dispatch_ready import DispatchServices

#: Envelope extras that need only the store and artifacts: the PRD
#: card's interview answers (feature 026), and an understanding
#: redraft's rejected restatement plus correction (feature 032).
_STORE_CONTEXTS: dict[
    str, Callable[[WorkCard, BoardStore, ArtifactsService], str]
] = {
    CardKind.PRD.value: lambda card, store, artifacts: (
        gather_refinement_context(card.workflow_id, store, artifacts)
    ),
    CardKind.UNDERSTANDING.value: understanding_context,
    CardKind.STRATEGIC_INTERVIEW.value: lambda _card, _store, _artifacts: (
        QUESTION_FORMAT
    ),
}



def routing_of(services: DispatchServices) -> RoutingServices:
    """Adapt :class:`DispatchServices` to the routes' bundle.

    :raises ValueError: If the coordinator or gates are not configured —
        callers check both first, so this never fires in practice.
    """
    if services.coordinator is None or services.gates is None:
        raise ValueError("routing needs a coordinator and gates")
    return RoutingServices(
        store=services.claims.store,
        coordinator=services.coordinator,
        gates=services.gates,
        artifacts=services.artifacts,
    )


def interview_of(services: DispatchServices) -> InterviewServices:
    """The interview modules' bundle (feature 038)."""
    return InterviewServices(routing_of(services), services.roster)


def extra_context_for(
    workflow_id: str, card: WorkCard, services: DispatchServices
) -> str:
    """Per-card-kind envelope extras (feature 026's ``prd`` interview
    context, feature 038's interview cards, feature 031's approved task
    for any card working on one).
    """
    retry = retry_context(card, services.claims.store)
    base = _context_for(workflow_id, card, services)
    return "\n\n".join(part for part in (retry, base) if part)


def _context_for(
    workflow_id: str, card: WorkCard, services: DispatchServices
) -> str:
    if card.task_node_id:
        return task_context(
            card, services.claims.store.list_cards(workflow_id),
            services.artifacts,
        )
    if card.kind in _STORE_CONTEXTS:
        return _STORE_CONTEXTS[card.kind](
            card, services.claims.store, services.artifacts
        )
    context = _ROUTED_CONTEXTS.get(card.kind)
    if context is None or not (services.coordinator and services.gates):
        return ""
    return context(workflow_id, card, services)


def _interview_context(
    workflow_id: str, card: WorkCard, services: DispatchServices
) -> str:
    """What an interviewer is told: its brief, its round, the answers
    another profile gave in its place, and the answer format."""
    gates = services.gates
    rounds = round_context(
        card, services.claims.store.list_cards(workflow_id),
        gates.get_gate, services.artifacts, gates.refinement_round_cap,
    )
    elsewhere = answered_elsewhere(card, interview_of(services))
    parts = (INTERVIEWER_BRIEF, rounds, elsewhere, QUESTION_FORMAT)
    return "\n\n".join(part for part in parts if part)


#: Envelope extras that need the coordinator and gates: estimation
#: (feature 030) and the interview's cards (feature 038).
_ROUTED_CONTEXTS: dict[
    str, Callable[[str, WorkCard, "DispatchServices"], str]
] = {
    CardKind.ESTIMATION.value: lambda _wid, card, services: (
        estimation_context(card, routing_of(services))
    ),
    CardKind.REFINEMENT.value: _interview_context,
    CardKind.INTERVIEW_PLAN.value: lambda _wid, card, services: (
        plan_context(card, interview_of(services))
    ),
    CardKind.QUESTION_REVIEW.value: lambda _wid, card, services: (
        review_context(card, interview_of(services))
    ),
}

_Route = Callable[[str, WorkCard, "DispatchServices"], None]


def _legacy_route(route: Callable[..., None]) -> _Route:
    """Adapt a ``(text, card, gates, artifacts)`` route."""
    return lambda text, card, services: route(
        text, card, services.gates, services.artifacts
    )


def _route_draft(text: str, card: WorkCard, services: DispatchServices) -> None:
    """Store an interviewer's questions, then review its batch once the
    whole batch has drafted (feature 038)."""
    try:
        route_refinement_result(
            text, card, services.gates, services.artifacts
        )
    finally:
        # An unreadable draft is retried or escalated, and its batch
        # must still move on without it once that is decided.
        after_draft(card, interview_of(services))


#: Card kind -> the follow-up router for its accepted result (research
#: R9). Every entry needs both the coordinator (to escalate) and gates
#: (to open the next human decision); a deployment without them leaves
#: these results generically accepted with no follow-up.
ROUTES: dict[str, _Route] = {
    CardKind.DECOMPOSITION.value: lambda text, card, services: (
        route_decomposition_result(text, card, routing_of(services))
    ),
    CardKind.ESTIMATION.value: lambda text, card, services: (
        route_estimation_result(text, card, routing_of(services))
    ),
    CardKind.REFINEMENT.value: _route_draft,
    CardKind.PRD.value: _legacy_route(route_prd_result),
    CardKind.STRATEGIC_INTERVIEW.value: _legacy_route(
        route_strategic_interview_result
    ),
    CardKind.UNDERSTANDING.value: _legacy_route(route_understanding_result),
    CardKind.INTERVIEW_PLAN.value: lambda text, card, services: (
        route_plan_result(text, card, interview_of(services))
    ),
    CardKind.QUESTION_REVIEW.value: lambda text, card, services: (
        route_review_result(text, card, interview_of(services))
    ),
}


def retry_or_escalate(
    card: WorkCard, error: UnreadableResultError, services: DispatchServices
) -> None:
    """Try *card*'s unreadable work again, or — once its automatic
    attempts are used up — escalate it to the coordinator, where the
    operator can retry it (feature 042)."""
    store = services.claims.store
    cards = store.list_cards(card.workflow_id)
    if retries_of(card, cards) < services.unreadable_retry_cap:
        attempt = retry_card(store, card)
        note_attempt(services, attempt, detail_of(error.reason))
        return
    if services.coordinator is not None:
        services.coordinator.apply_actions(
            card.workflow_id, f"unreadable:{card.id}:{card.attempt_count}",
            [
                CreateCardAction(
                    kind=CardKind.COORDINATOR_REVIEW.value,
                    title=error.title, source_card_id=card.id,
                )
            ],
        )


def note_attempt(
    services: DispatchServices, attempt: WorkCard, payload: str
) -> None:
    """Record an automatic attempt and why — waking dispatch when the
    board can."""
    if services.board is not None:
        services.board.record_attempt(attempt, AUTOMATIC, payload)
        return
    services.claims.store.append_event(
        BoardEventRecord(
            workflow_id=attempt.workflow_id, card_id=attempt.id,
            event_type=AUTOMATIC, payload=payload,
        )
    )
