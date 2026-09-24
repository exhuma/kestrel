"""Event-driven specialist claiming, card-turn dispatch, and coordinator
wake-up tests (feature 026, T034).

Two independent mechanics: ``claim_and_dispatch`` claims one ready card
for a specialist and runs its turn (raw dispatch, no artifact storage —
that is a later phase's concern, see ``app/services/board/artifacts.py``
module docstring); ``SchedulingService.wake`` runs the coordinator's own
turn and applies whatever it proposes, idempotently per board revision
(FR-004's event-driven wake conditions).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.backends.base import TurnRequest, TurnResult
from app.models_board import SpecialistDefinition, WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_store import BoardStore
from app.services.board.claims import ClaimsService, NoEligibleCardError
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch import (
    CardTurnError,
    SchedulingService,
    build_card_envelope,
    build_coordinator_envelope,
    claim_and_dispatch,
    run_card_turn,
)
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)


class _FakeBackend:
    """A minimal backend double: only ``run_turn`` is exercised here."""

    def __init__(
        self, final_text: str = "", *, delay: float = 0.0, raises: bool = False
    ) -> None:
        self._final_text = final_text
        self._delay = delay
        self._raises = raises
        self.last_request: TurnRequest | None = None

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        self.last_request = req
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise RuntimeError("backend exploded")
        return TurnResult(session_id="turn-1", final_text=self._final_text)


def _specialist(role_id: str = "developer") -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id,
        label=role_id,
        purpose="test role",
        allowed_card_types=("analysis",),
        required_abilities=(),
        model_policy="default",
        workspace_permission="read_only",
        retry_limit=1,
        prompt="You are the developer specialist.",
    )


def _coordinator_specialist() -> SpecialistDefinition:
    return SpecialistDefinition(
        id="coordinator",
        label="coordinator",
        purpose="plans work",
        allowed_card_types=(),
        required_abilities=(),
        model_policy="default",
        workspace_permission="none",
        retry_limit=1,
        prompt="You are the COORDINATOR.",
    )




def _scheduling_service(tmp_path: Path) -> tuple[SchedulingService, BoardStore]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    coordinator_store = BoardCoordinatorStore(factory)
    board_service = BoardService(store)
    roster = SpecialistRoster(
        {"developer": _specialist(), "coordinator": _coordinator_specialist()}
    )
    coordinator = CoordinatorService(store, coordinator_store, board_service)
    store.create_workflow(_WORKFLOW)
    scheduling = SchedulingService(
        store, roster, coordinator, default_timeout_seconds=5
    )
    return scheduling, store


class TestCardEnvelope:
    """The card envelope carries the specialist's prompt and card context."""

    def test_envelope_includes_prompt_and_card_context(self) -> None:
        specialist = _specialist()
        card = WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate the bug",
            state="claimed",
        )
        envelope = build_card_envelope(specialist, card)
        assert "You are the developer specialist." in envelope
        assert "Investigate the bug" in envelope
        assert "analysis" in envelope


class TestCardTurn:
    """A card turn either yields a result or fails closed."""

    @pytest.mark.asyncio
    async def test_successful_turn_returns_final_text(self) -> None:
        backend = _FakeBackend("<RESULT>done</RESULT>")
        result = await run_card_turn(
            backend, "envelope", cwd="/tmp", timeout_seconds=5
        )
        assert result.final_text == "<RESULT>done</RESULT>"

    @pytest.mark.asyncio
    async def test_timeout_raises_card_turn_error(self) -> None:
        backend = _FakeBackend(delay=10)
        with pytest.raises(CardTurnError):
            await run_card_turn(
                backend, "envelope", cwd="/tmp", timeout_seconds=0.01
            )

    @pytest.mark.asyncio
    async def test_backend_error_raises_card_turn_error(self) -> None:
        backend = _FakeBackend(raises=True)
        with pytest.raises(CardTurnError):
            await run_card_turn(
                backend, "envelope", cwd="/tmp", timeout_seconds=5
            )


class TestClaimAndDispatch:
    """Claiming and dispatching a turn for one ready card."""

    @pytest.mark.asyncio
    async def test_claims_and_dispatches_the_eligible_card(
        self, tmp_path: Path
    ) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        claims_store = BoardClaimsStore(factory)
        store.create_workflow(_WORKFLOW)
        store.create_card(
            WorkCard(
                id="card-1",
                workflow_id="wf-1",
                kind="analysis",
                title="Investigate",
                state="ready",
                eligible_roles=("developer",),
            )
        )
        claims = ClaimsService(
            store=store,
            claims_store=claims_store,
            roster=SpecialistRoster({"developer": _specialist()}),
            max_parallel_read_cards=4,
            default_lease_seconds=60,
            default_workspace_lease_seconds=600,
        )
        backend = _FakeBackend("<RESULT>ok</RESULT>")

        outcome = await claim_and_dispatch(
            claims,
            "wf-1",
            _specialist(),
            backend,
            timeout_seconds=5,
        )

        assert outcome is not None
        card, result = outcome
        assert card.id == "card-1"
        assert result.final_text == "<RESULT>ok</RESULT>"
        prompt = backend.last_request.prompt
        assert "You are the developer specialist." in prompt

    @pytest.mark.asyncio
    async def test_no_ready_work_returns_none(self, tmp_path: Path) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        claims_store = BoardClaimsStore(factory)
        store.create_workflow(_WORKFLOW)
        claims = ClaimsService(
            store=store,
            claims_store=claims_store,
            roster=SpecialistRoster({"developer": _specialist()}),
            max_parallel_read_cards=4,
            default_lease_seconds=60,
            default_workspace_lease_seconds=600,
        )
        backend = _FakeBackend("<RESULT>ok</RESULT>")

        outcome = await claim_and_dispatch(
            claims,
            "wf-1",
            _specialist(),
            backend,
            timeout_seconds=5,
        )

        assert outcome is None


class TestCoordinatorEnvelope:
    """The coordinator envelope summarizes the workflow's current cards."""

    def test_envelope_includes_prompt_and_card_summary(self) -> None:
        specialist = _coordinator_specialist()
        workflow = _WORKFLOW
        cards = [
            WorkCard(
                id="card-1",
                workflow_id="wf-1",
                kind="analysis",
                title="Investigate",
                state="ready",
            )
        ]
        envelope = build_coordinator_envelope(specialist, workflow, cards)
        assert "You are the COORDINATOR." in envelope
        assert "card-1" in envelope
        assert "ready" in envelope


class TestSchedulingServiceWake:
    """Waking the coordinator applies whatever it validly proposes."""

    @pytest.mark.asyncio
    async def test_wake_applies_a_valid_proposed_action(
        self, tmp_path: Path
    ) -> None:
        service, store = _scheduling_service(tmp_path)
        backend = _FakeBackend(
            '<COORDINATOR_ACTIONS>{"actions": ['
            '{"type": "create_card", "kind": "analysis", "title": "Look"}'
            "]}</COORDINATOR_ACTIONS>"
        )

        await service.wake("wf-1", backend)

        titles = {c.title for c in store.list_cards("wf-1")}
        assert "Look" in titles

    @pytest.mark.asyncio
    async def test_wake_is_a_no_op_when_the_coordinator_proposes_nothing(
        self, tmp_path: Path
    ) -> None:
        service, store = _scheduling_service(tmp_path)
        backend = _FakeBackend("no structured block here")

        await service.wake("wf-1", backend)

        assert store.list_cards("wf-1") == []

    @pytest.mark.asyncio
    async def test_wake_does_not_reprocess_an_unchanged_revision(
        self, tmp_path: Path
    ) -> None:
        service, store = _scheduling_service(tmp_path)
        backend = _FakeBackend(
            '<COORDINATOR_ACTIONS>{"actions": ['
            '{"type": "create_card", "kind": "analysis", "title": "Once"}'
            "]}</COORDINATOR_ACTIONS>"
        )

        await service.wake("wf-1", backend)
        await service.wake("wf-1", backend)

        matching = [c for c in store.list_cards("wf-1") if c.title == "Once"]
        assert len(matching) == 1


def test_claims_service_no_eligible_card_error_is_importable() -> None:
    """Sanity import check: dispatch.py depends on this error type too."""
    assert issubclass(NoEligibleCardError, Exception)
