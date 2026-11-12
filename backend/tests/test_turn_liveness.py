"""An agent turn runs while its agent works, its card stays claimed while
it runs, and a failed turn frees its card at once."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.backends.base import TurnRequest, TurnResult
from app.backends.opencode_permissions import _session_of
from app.config import Settings
from app.config_models import BackendConfig
from app.models_board import WorkCard
from app.services.board.claim_heartbeat import kept_claimed
from app.services.board.dispatch import CardTurnError, run_card_turn
from app.services.board.specialists import SpecialistRoster
from app.services.board.turn_limits import TurnLimits
from tests.test_board_scheduling import _dispatch_services, _specialist

_TICK = 0.02


class _Agent:
    """Reports activity every *every* seconds for *busy* seconds, then
    answers; or never reports anything when *every* is ``None``."""

    def __init__(self, busy: float, every: float | None) -> None:
        self._busy, self._every = busy, every

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        loop = asyncio.get_running_loop()
        end = loop.time() + self._busy
        while loop.time() < end:
            await asyncio.sleep(self._every or self._busy)
            if self._every and req.on_activity is not None:
                req.on_activity()
        return TurnResult(session_id="s", final_text="done")


def _request() -> TurnRequest:
    return TurnRequest(prompt="p", cwd="", permission_mode="read_only")


@pytest.mark.asyncio
async def test_a_busy_turn_outlives_the_idle_limit() -> None:
    """Ensure a long turn that keeps working is not stopped."""
    result = await run_card_turn(
        _Agent(busy=0.3, every=_TICK), _request(),
        limits=TurnLimits(idle_seconds=0.1, max_seconds=5),
    )

    assert result.final_text == "done"


@pytest.mark.asyncio
async def test_a_silent_turn_is_stopped_at_the_idle_limit() -> None:
    """Ensure a hung turn ends after the idle limit, saying so."""
    with pytest.raises(CardTurnError, match="made no progress for 0.1"):
        await run_card_turn(
            _Agent(busy=5, every=None), _request(),
            limits=TurnLimits(idle_seconds=0.1, max_seconds=5),
        )


@pytest.mark.asyncio
async def test_a_busy_turn_is_stopped_at_the_ceiling() -> None:
    """Ensure activity alone cannot keep a turn running for ever."""
    with pytest.raises(CardTurnError, match="ran past its limit"):
        await run_card_turn(
            _Agent(busy=5, every=_TICK), _request(),
            limits=TurnLimits(idle_seconds=1, max_seconds=0.2),
        )


def _claimed(tmp_path: Path, attempts: int = 1, lease: float = 60.0):
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    services = replace(
        services, claims=replace(services.claims, default_lease_seconds=lease)
    )
    store.create_card(WorkCard(
        id="card-1", workflow_id="wf-1", kind="analysis", title="Look",
        state="ready", eligible_roles=("developer",), attempt_limit=attempts,
    ))
    card = services.claims.claim_next_ready_card("wf-1", "developer")
    return services.claims, store, card


def test_a_failed_attempt_with_attempts_left_is_ready_at_once(
    tmp_path: Path,
) -> None:
    """Ensure a retry does not wait for the lease to run out."""
    claims, store, card = _claimed(tmp_path, attempts=2)

    assert claims.end_failed(card) == "ready"
    assert store.get_card("card-1").state == "ready"
    assert claims.claims_store.get_active_lease("card-1") is None


def test_a_last_failed_attempt_fails_the_card(tmp_path: Path) -> None:
    """Ensure the attempt limit still holds."""
    claims, store, card = _claimed(tmp_path, attempts=1)

    assert claims.end_failed(card) == "failed"
    assert claims.end_failed(card) is None  # already ended


@pytest.mark.asyncio
async def test_a_running_turn_keeps_its_claim(tmp_path: Path) -> None:
    """Ensure the lease is renewed while the turn runs, and not after."""
    claims, _store, card = _claimed(tmp_path, lease=3.0)
    first = claims.claims_store.get_active_lease("card-1").expires_at

    async with kept_claimed(claims, card):
        await asyncio.sleep(1.2)

    renewed = claims.claims_store.get_active_lease("card-1").expires_at
    assert renewed > first


def test_a_claim_taken_over_is_not_renewed(tmp_path: Path) -> None:
    """Ensure renewal only extends the attempt that still holds it."""
    claims, _store, card = _claimed(tmp_path)
    claims.end_failed(card)

    assert claims.renew(card) is False


@pytest.mark.parametrize("props", [
    {"sessionID": "s1"},
    {"part": {"sessionID": "s1", "type": "text"}},
    {"info": {"sessionID": "s1"}},
])
def test_an_opencode_event_is_matched_to_its_session(props: dict) -> None:
    """Ensure activity counts however the event names its session."""
    assert _session_of(props) == "s1"


def test_the_removed_turn_timeout_names_its_replacements(
    tmp_path: Path,
) -> None:
    """Ensure an old config file says what to use instead."""
    config = tmp_path / "config.toml"
    config.write_text("board_turn_timeout_seconds = 600\n")

    with pytest.raises(ValueError, match="board_turn_idle_seconds"):
        Settings(_env_file=None, config_file=str(config))


def test_a_backend_timeout_is_refused_with_the_reason() -> None:
    """Ensure a leftover backend timeout fails with an explanation."""
    with pytest.raises(ValueError, match="board_turn_max_seconds"):
        BackendConfig(id="oc", type="opencode", timeout=600)
