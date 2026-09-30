"""Another attempt at work whose result could not be read (feature 042),
through the real dispatch loop and the operator's intervention."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from app.models_board import CardAction, CardRelation, WorkCard
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.gates import GatesService
from app.services.board.interventions import (
    InterventionsService,
    allowed_actions_for,
)
from app.services.board.retries import live_attempts
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory
from tests.test_board_decomposition import _WORKFLOW
from tests.test_board_scheduling import _FakeBackend, _specialist

_MALFORMED = '<DECOMPOSITION>{"summary": "x", "tasks": [}</DECOMPOSITION>'


@dataclass
class _Rig:
    store: BoardStore
    services: DispatchServices
    interventions: InterventionsService
    backend: _FakeBackend

    async def turn(self) -> None:
        await dispatch_ready_work(
            "wf-1", self.services, lambda _s: self.backend,
            timeout_seconds=5,
        )

    def cards(self) -> list[WorkCard]:
        return self.store.list_cards("wf-1")

    def open_of(self, kind: str) -> WorkCard:
        (card,) = [
            c for c in self.cards() if c.kind == kind and c.state == "ready"
        ]
        return card


def _rig(tmp_path: Path, *, cap: int = 1) -> _Rig:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    board = BoardService(store)
    pm = replace(_specialist("pm"), allowed_card_types=("decomposition",))
    roster = SpecialistRoster({"pm": pm})
    artifacts = ArtifactsService(
        store, BoardArtifactStore(factory), board,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    gates = GatesService(store, BoardGateStore(factory), board, artifacts)
    store.create_workflow(_WORKFLOW)
    store.create_card(WorkCard(
        id="prd", workflow_id="wf-1", kind="prd", title="PRD", state="done",
    ))
    store.create_card(WorkCard(
        id="card-1", workflow_id="wf-1", kind="decomposition",
        title="Decompose", state="ready", eligible_roles=("pm",),
    ))
    store.add_relation(CardRelation("card-1", "prd"))
    claims = ClaimsService(
        store=store, claims_store=claims_store, roster=roster,
        max_parallel_read_cards=4, default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )
    services = DispatchServices(
        claims, roster, artifacts,
        coordinator=CoordinatorService(
            store, BoardCoordinatorStore(factory), board
        ),
        gates=gates, board=board, unreadable_retry_cap=cap,
    )
    interventions = InterventionsService(store, claims_store, board, gates)
    return _Rig(store, services, interventions, _FakeBackend(_MALFORMED))


@pytest.mark.asyncio
async def test_an_unreadable_result_is_tried_again_with_the_reason(
    tmp_path: Path,
) -> None:
    """Ensure malformed output runs the same work again, told why."""
    rig = _rig(tmp_path)

    await rig.turn()

    retry = rig.open_of("decomposition")
    assert (retry.source_card_id, retry.eligible_roles) == ("card-1", ("pm",))
    assert [
        r.depends_on_card_id for r in rig.store.list_relations("wf-1")
        if r.card_id == retry.id
    ] == ["prd"]
    assert "coordinator_review" not in [c.kind for c in rig.cards()]
    await rig.turn()
    assert "could not be used: malformed result" in (
        rig.backend.last_request.prompt
    )


@pytest.mark.asyncio
async def test_past_the_cap_it_escalates_for_the_operator(
    tmp_path: Path,
) -> None:
    """Ensure the automatic attempts are bounded, then escalated with
    the last attempt as its source."""
    rig = _rig(tmp_path)

    await rig.turn()
    retry = rig.open_of("decomposition")
    await rig.turn()

    review = rig.open_of("coordinator_review")
    assert review.source_card_id == retry.id
    assert "Unparseable decomposition proposal" in review.title


@pytest.mark.asyncio
async def test_a_zero_cap_escalates_at_once(tmp_path: Path) -> None:
    rig = _rig(tmp_path, cap=0)

    await rig.turn()

    assert rig.open_of("coordinator_review").source_card_id == "card-1"


@pytest.mark.asyncio
async def test_the_operator_retries_from_the_escalation(
    tmp_path: Path,
) -> None:
    """Ensure the escalation offers Retry, which runs the work again and
    closes the escalation."""
    rig = _rig(tmp_path, cap=0)
    await rig.turn()
    review = rig.open_of("coordinator_review")
    assert CardAction.RETRY in allowed_actions_for(review)

    closed = rig.interventions.apply(
        "wf-1", review.id, CardAction.RETRY,
        expected_revision=rig.store.get_workflow("wf-1").revision,
    )

    assert closed.state == "done"
    assert rig.open_of("decomposition").source_card_id == "card-1"
    assert CardAction.RETRY not in allowed_actions_for(closed)


def test_a_replaced_attempt_is_not_counted() -> None:
    """Ensure a retried interview does not use up a round."""
    first = WorkCard(
        id="a", workflow_id="wf-1", kind="refinement", title="pm",
        state="done", eligible_roles=("pm",),
    )
    retry = WorkCard(
        id="b", workflow_id="wf-1", kind="refinement", title="pm",
        state="ready", eligible_roles=("pm",), source_card_id="a",
    )
    review = WorkCard(
        id="c", workflow_id="wf-1", kind="coordinator_review",
        title="r", state="ready", source_card_id="b",
    )

    assert [c.id for c in live_attempts([first, retry, review])] == [
        "b", "c"
    ]
