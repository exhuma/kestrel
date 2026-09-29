"""Ready work is never stranded by one failed scheduling pass (#69)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models_board import WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board import bootstrap
from app.services.board.dispatch import CardTurnError
from app.services.board.recovery import RecoveryService
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory
from tests.test_board_scheduling import _FakeBackend, _scheduling_service


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
    monkeypatch.setattr(
        bootstrap, "get_specialist_backend_policy",
        lambda: SimpleNamespace(backend_for=None),
    )

    await bootstrap._wake_and_dispatch("wf-1", object())

    assert dispatched == ["wf-1"]


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
