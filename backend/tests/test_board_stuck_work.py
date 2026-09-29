"""Ready work is never stranded by one failed scheduling pass (#69)."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models_board import WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board import bootstrap
from app.services.board.dispatch import CardTurnError
from app.services.board.dispatch_ready import dispatch_ready_work
from app.services.board.live_activity import LiveActivity
from app.services.board.recovery import RecoveryService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory
from tests.test_board_scheduling import (
    _dispatch_services,
    _FakeBackend,
    _scheduling_service,
    _specialist,
)


def _recovery(
    tmp_path: Path, *cards: tuple[str, str, tuple[str, ...]]
) -> tuple[RecoveryService, list[str]]:
    """A recovery sweep over one workflow holding *cards*."""
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    store.create_workflow(
        Workflow(
            id="wf-1", source="github-issue", task_ref="o/r#1", repo="o/r",
            base_branch="main", source_visibility="public", title="t",
        )
    )
    for index, (kind, state, roles) in enumerate(cards):
        store.create_card(
            WorkCard(
                id=f"card-{index}", workflow_id="wf-1", kind=kind,
                title=kind, state=state, eligible_roles=roles,
            )
        )
    nudged: list[str] = []
    service = RecoveryService(
        BoardClaimsStore(factory), BoardService(store),
        interval_seconds=60, nudge=nudged.append,
    )
    return service, nudged


def test_a_waiting_ready_card_is_nudged(tmp_path: Path) -> None:
    """Ensure an unclaimed understanding card gets another dispatch."""
    service, nudged = _recovery(
        tmp_path,
        ("security_review", "done", ()),
        ("understanding", "ready", ("pm",)),
    )

    service.nudge_waiting_work()

    assert nudged == ["wf-1"]


@pytest.mark.parametrize(
    "cards",
    [
        [("understanding", "ready", ("pm",)), ("analysis", "claimed", ("x",))],
        [("delivery", "ready", ())],
        [("understanding_gate", "awaiting_human", ())],
    ],
    ids=["work-in-progress", "system-card", "waiting-for-the-operator"],
)
def test_nothing_is_nudged_when_nothing_can_move(
    tmp_path: Path, cards: list[tuple[str, str, tuple[str, ...]]]
) -> None:
    service, nudged = _recovery(tmp_path, *cards)

    service.nudge_waiting_work()

    assert nudged == []


@pytest.mark.asyncio
async def test_dispatch_runs_even_when_the_coordinator_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure a coordinator failure no longer strands ready cards."""
    dispatched: list[str] = []

    async def failing_wake(_workflow_id, _backend) -> None:
        raise CardTurnError("card turn timed out")

    async def dispatch(workflow_id, *_args, **_kwargs) -> None:
        dispatched.append(workflow_id)

    monkeypatch.setattr(
        bootstrap, "get_scheduling_service",
        lambda: SimpleNamespace(wake=failing_wake),
    )
    monkeypatch.setattr(bootstrap, "dispatch_ready_work", dispatch)
    monkeypatch.setattr(bootstrap, "get_dispatch_services", lambda: None)
    problems: list[dict] = []
    monkeypatch.setattr(
        bootstrap, "get_board_service",
        lambda: SimpleNamespace(
            record_problem=lambda wid, **kw: problems.append({wid: kw})
        ),
    )
    monkeypatch.setattr(
        bootstrap, "get_specialist_backend_policy",
        lambda: SimpleNamespace(backend_for=None),
    )

    await bootstrap._wake_and_dispatch("wf-1", object())

    assert dispatched == ["wf-1"]
    # ...and the request says why nothing came from the coordinator (033).
    assert problems == [{"wf-1": {
        "event_type": "coordinator.turn_failed",
        "detail": "the coordinator's turn timed out",
    }}]


@pytest.mark.asyncio
async def test_a_failed_coordinator_turn_is_retried(tmp_path: Path) -> None:
    """Ensure a timed-out turn does not count as having handled its
    revision, so the next nudge wakes the coordinator again."""
    service, _store = _scheduling_service(tmp_path)

    with pytest.raises(CardTurnError):
        await service.wake("wf-1", _FakeBackend(raises=True))
    backend = _FakeBackend("")
    await service.wake("wf-1", backend)

    assert backend.last_request is not None


def test_turns_get_their_own_timeout() -> None:
    """Ensure agent turns no longer inherit the 30 s screening timeout."""
    settings = Settings(_env_file=None)
    screening, turn = 30.0, 600.0

    assert settings.board_input_security_timeout_seconds == screening
    assert settings.board_turn_timeout_seconds == turn


@pytest.mark.asyncio
async def test_a_failed_card_turn_is_recorded_on_the_request(
    tmp_path: Path,
) -> None:
    """Ensure a specialist's failed turn is visible, not only logged, and
    that the card is live only while its turn runs (feature 033)."""
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    live = LiveActivity()
    seen_live: list[str | None] = []

    class _Failing(_FakeBackend):
        async def run_turn(self, _req):
            turn = live.current("wf-1")
            seen_live.append(turn.subject if turn else None)
            raise RuntimeError("backend exploded")

    services = replace(services, board=BoardService(store), live=live)
    store.create_card(
        WorkCard(
            id="card-1", workflow_id="wf-1", kind="analysis",
            title="Investigate", state="ready", eligible_roles=("developer",),
        )
    )

    await dispatch_ready_work(
        "wf-1", services, lambda _s: _Failing(), timeout_seconds=5
    )

    assert seen_live == ["Investigate"]  # live only during the turn
    assert live.current("wf-1") is None
    (event,) = [
        e for e in store.list_events("wf-1")
        if e.event_type == "card.turn_failed"
    ]
    assert event.card_id == "card-1"
    assert json.loads(event.payload) == {
        "detail": "developer's turn failed; see the kestrel log"
    }
