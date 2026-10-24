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
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_store import BoardStore
from app.policy import SpecialistCapabilityError
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.claims import ClaimsService, NoEligibleCardError
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch import (
    CardTurnError,
    SchedulingService,
    card_request,
    claim_and_dispatch,
    run_card_turn,
)
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
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
    artifacts = ArtifactsService(
        store, BoardArtifactStore(factory), board_service,
        BoardArtifactContentStore(tmp_path / "artifacts"),
    )
    store.create_workflow(_WORKFLOW)
    scheduling = SchedulingService(
        store, roster, coordinator, artifacts, default_timeout_seconds=5
    )
    return scheduling, store


class TestCardTurn:
    """A card turn either yields a result or fails closed."""

    @pytest.mark.asyncio
    async def test_successful_turn_returns_final_text(self) -> None:
        backend = _FakeBackend("<RESULT>done</RESULT>")
        result = await run_card_turn(
            backend, card_request("envelope", cwd="/tmp"), timeout_seconds=5
        )
        assert result.final_text == "<RESULT>done</RESULT>"

    @pytest.mark.asyncio
    async def test_timeout_raises_card_turn_error(self) -> None:
        backend = _FakeBackend(delay=10)
        with pytest.raises(CardTurnError):
            await run_card_turn(
                backend,
                card_request("envelope", cwd="/tmp"),
                timeout_seconds=0.01,
            )

    @pytest.mark.asyncio
    async def test_backend_error_raises_card_turn_error(self) -> None:
        backend = _FakeBackend(raises=True)
        with pytest.raises(CardTurnError):
            await run_card_turn(
                backend, card_request("envelope", cwd="/tmp"), timeout_seconds=5
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
    async def test_wake_includes_pending_prd_rejection_feedback(
        self, tmp_path: Path
    ) -> None:
        """Feature 028: the coordinator's envelope must carry a pending
        PRD rejection's feedback, not just the review card's title —
        that's what lets it judge fix-vs-reinterview."""
        service, store = _scheduling_service(tmp_path)
        gate = WorkCard(
            id="gate-1", workflow_id="wf-1", kind="prd_gate",
            title="Approve PRD", state="cancelled",
        )
        store.create_card(gate)
        service._artifacts.store_reference_artifact(
            ArtifactDraft(
                producer_card_id="gate-1", logical_name="response",
                revision=1, content="Too vague on scope.",
                trust="operator_approved",
            )
        )
        backend = _FakeBackend("no structured block here")

        await service.wake("wf-1", backend)

        assert backend.last_request is not None
        assert "Too vague on scope." in backend.last_request.prompt

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


class _CountingBackend(_FakeBackend):
    """Counts the coordinator turns actually sent to the model."""

    def __init__(self) -> None:
        super().__init__("", delay=0.05)
        self.turns = 0

    async def run_turn(self, req: TurnRequest) -> TurnResult:
        self.turns += 1
        return await super().run_turn(req)


@pytest.mark.asyncio
async def test_a_burst_of_wakes_costs_one_turn_per_revision(
    tmp_path: Path,
) -> None:
    """Ensure concurrent wakes for one board revision make one LLM call,
    and a changed board is woken for again (#66)."""
    service, store = _scheduling_service(tmp_path)
    backend = _CountingBackend()

    await asyncio.gather(*(service.wake("wf-1", backend) for _ in range(5)))
    assert backend.turns == 1

    store.bump_workflow_revision("wf-1")
    await service.wake("wf-1", backend)
    second_revision_turns = 2
    assert backend.turns == second_revision_turns


def test_claims_service_no_eligible_card_error_is_importable() -> None:
    """Sanity import check: dispatch.py depends on this error type too."""
    assert issubclass(NoEligibleCardError, Exception)


def _dispatch_services(tmp_path: Path, roster: SpecialistRoster) -> tuple[
    DispatchServices, BoardStore
]:
    """A DispatchServices bundle over a fresh board with one workflow."""
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    board_service = BoardService(store)
    artifact_store = BoardArtifactStore(factory)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    store.create_workflow(_WORKFLOW)
    claims = ClaimsService(
        store=store,
        claims_store=claims_store,
        roster=roster,
        max_parallel_read_cards=4,
        default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )
    artifacts = ArtifactsService(
        store, artifact_store, board_service, content_store
    )
    return DispatchServices(claims, roster, artifacts), store


class TestDispatchReadyWork:
    """T034: the previously-missing automatic claim-and-turn loop."""

    @pytest.mark.asyncio
    async def test_claims_turns_and_accepts_the_eligible_card(
        self, tmp_path: Path
    ) -> None:
        roster = SpecialistRoster({"developer": _specialist()})
        services, store = _dispatch_services(tmp_path, roster)
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
        backend = _FakeBackend("<RESULT>the finding</RESULT>")

        await dispatch_ready_work(
            "wf-1", services, lambda _specialist: backend, timeout_seconds=5
        )

        card = store.get_card("card-1")
        assert card.state == "done"

    @pytest.mark.asyncio
    async def test_the_coordinator_claims_only_its_own_card_kinds(
        self, tmp_path: Path
    ) -> None:
        """Ensure the coordinator is dispatched for its interview cards
        (feature 038) and nothing else."""
        roster = SpecialistRoster(
            {
                "developer": _specialist(),
                "coordinator": _coordinator_specialist(),
            }
        )
        services, store = _dispatch_services(tmp_path, roster)
        store.create_card(WorkCard(
            id="card-1", workflow_id="wf-1", kind="analysis",
            title="Not the coordinator's", state="ready",
            eligible_roles=("coordinator",),
        ))

        await dispatch_ready_work(
            "wf-1", services, lambda _s: _FakeBackend("<RESULT>ok</RESULT>"),
            timeout_seconds=5,
        )

        assert store.get_card("card-1").state == "ready"

    @pytest.mark.asyncio
    async def test_one_specialists_capability_error_does_not_block_others(
        self, tmp_path: Path
    ) -> None:
        roster = SpecialistRoster(
            {"developer": _specialist(), "requester": _specialist("requester")}
        )
        services, store = _dispatch_services(tmp_path, roster)
        store.create_card(
            WorkCard(
                id="card-1",
                workflow_id="wf-1",
                kind="analysis",
                title="Investigate",
                state="ready",
                eligible_roles=("requester",),
            )
        )
        backend = _FakeBackend("<RESULT>ok</RESULT>")

        def _backend_for(specialist: SpecialistDefinition) -> _FakeBackend:
            if specialist.id == "developer":
                raise SpecialistCapabilityError(
                    "developer", "claude", frozenset()
                )
            return backend

        await dispatch_ready_work(
            "wf-1", services, _backend_for, timeout_seconds=5
        )

        assert store.get_card("card-1").state == "done"

    @pytest.mark.asyncio
    async def test_backend_failure_leaves_card_claimed_for_recovery(
        self, tmp_path: Path
    ) -> None:
        roster = SpecialistRoster({"developer": _specialist()})
        services, store = _dispatch_services(tmp_path, roster)
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
        backend = _FakeBackend(raises=True)

        await dispatch_ready_work(
            "wf-1", services, lambda _specialist: backend, timeout_seconds=5
        )

        assert store.get_card("card-1").state == "claimed"
