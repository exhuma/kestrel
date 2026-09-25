"""Tests for verifier-finding routing into remediation/escalation cards
(feature 026, T051, FR-027/FR-028).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import SpecialistDefinition, WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_projection_store import BoardProjectionStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.projections import ProjectionsService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.board.verification import route_verifier_result
from tests.board_test_support import board_session_factory
from tests.test_board_scheduling import _FakeBackend


def _findings_block(*entries: str) -> str:
    return (
        '<VERIFIER_FINDINGS>{"findings": [' + ",".join(entries) + "]}"
        "</VERIFIER_FINDINGS>"
    )


def _setup(tmp_path: Path) -> tuple[CoordinatorService, BoardStore, WorkCard]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    coordinator_store = BoardCoordinatorStore(factory)
    board_service = BoardService(store)
    store.create_workflow(
        Workflow(
            id="wf-1",
            source="github-issue",
            task_ref="owner/repo#1",
            repo="owner/repo",
            base_branch="main",
            source_visibility="public",
            title="Add a thing",
        )
    )
    card = WorkCard(
        id="card-1",
        workflow_id="wf-1",
        kind="verification",
        title="Verify",
        state="review",
        attempt_count=1,
    )
    store.create_card(card)
    coordinator = CoordinatorService(store, coordinator_store, board_service)
    return coordinator, store, card


class TestRemediationRouting:
    def test_a_remediation_finding_creates_a_ready_implementation_card(
        self, tmp_path: Path
    ) -> None:
        coordinator, store, card = _setup(tmp_path)
        text = _findings_block(
            '{"category": "nonconformance", "summary": "missing null check"}'
        )

        route_verifier_result(text, card, coordinator)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "implementation"
        assert new_cards[0].state == "ready"
        assert new_cards[0].eligible_roles == ("coder",)
        assert new_cards[0].workspace_permission == "write"
        assert "missing null check" in new_cards[0].title


class TestEscalationRouting:
    def test_an_escalation_finding_creates_a_coordinator_review_card(
        self, tmp_path: Path
    ) -> None:
        coordinator, store, card = _setup(tmp_path)
        text = _findings_block(
            '{"category": "ambiguity", "summary": "unclear boundary"}'
        )

        route_verifier_result(text, card, coordinator)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"
        assert new_cards[0].eligible_roles == ()
        assert "unclear boundary" in new_cards[0].title

    def test_an_unparseable_result_escalates_fail_closed(
        self, tmp_path: Path
    ) -> None:
        coordinator, store, card = _setup(tmp_path)

        route_verifier_result("no structured block here", card, coordinator)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"


class TestMixedAndEmptyResults:
    def test_mixed_findings_create_one_card_each(self, tmp_path: Path) -> None:
        coordinator, store, card = _setup(tmp_path)
        text = _findings_block(
            '{"category": "nonconformance", "summary": "bug"}',
            '{"category": "policy_risk", "summary": "risky"}',
        )

        route_verifier_result(text, card, coordinator)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert sorted(c.kind for c in new_cards) == [
            "coordinator_review", "implementation",
        ]

    def test_a_clean_result_creates_no_follow_up_cards(
        self, tmp_path: Path
    ) -> None:
        coordinator, store, card = _setup(tmp_path)

        route_verifier_result(_findings_block(), card, coordinator)

        assert [c.id for c in store.list_cards("wf-1")] == [card.id]


class TestVerificationRoutingClean:
    """T069: whether a routed result signals "clean" (trigger delivery)."""

    def test_no_findings_is_clean(self, tmp_path: Path) -> None:
        coordinator, _store, card = _setup(tmp_path)

        routing = route_verifier_result(_findings_block(), card, coordinator)

        assert routing.clean is True
        assert routing.escalations == []

    def test_a_remediation_finding_is_not_clean(self, tmp_path: Path) -> None:
        coordinator, _store, card = _setup(tmp_path)
        text = _findings_block(
            '{"category": "nonconformance", "summary": "bug"}'
        )

        routing = route_verifier_result(text, card, coordinator)

        assert routing.clean is False

    def test_an_escalation_finding_is_not_clean(self, tmp_path: Path) -> None:
        coordinator, _store, card = _setup(tmp_path)
        text = _findings_block(
            '{"category": "ambiguity", "summary": "unclear"}'
        )

        routing = route_verifier_result(text, card, coordinator)

        assert routing.clean is False

    def test_an_unparseable_result_is_not_clean(self, tmp_path: Path) -> None:
        coordinator, _store, card = _setup(tmp_path)

        routing = route_verifier_result(
            "no structured block here", card, coordinator
        )

        assert routing.clean is False


class TestIdempotency:
    def test_routing_the_same_attempt_twice_does_not_duplicate_cards(
        self, tmp_path: Path
    ) -> None:
        coordinator, store, card = _setup(tmp_path)
        text = _findings_block(
            '{"category": "nonconformance", "summary": "bug"}'
        )

        route_verifier_result(text, card, coordinator)
        route_verifier_result(text, card, coordinator)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1


def _verifier() -> SpecialistDefinition:
    return SpecialistDefinition(
        id="verifier",
        label="verifier",
        purpose="test role",
        allowed_card_types=("verification",),
        required_abilities=(),
        model_policy="default",
        workspace_permission="read_only",
        retry_limit=1,
        prompt="You are the verifier.",
    )


class TestEndToEndDispatchRouting:
    """A verification card's turn result creates a follow-up card through
    the real dispatch_ready_work loop, not just route_verifier_result
    called directly."""

    @pytest.mark.asyncio
    async def test_a_verifier_turn_with_a_nonconformance_creates_remediation(
        self, tmp_path: Path,
    ) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        claims_store = BoardClaimsStore(factory)
        coordinator_store = BoardCoordinatorStore(factory)
        board_service = BoardService(store)
        artifact_store = BoardArtifactStore(factory)
        content_store = BoardArtifactContentStore(tmp_path / "artifacts")
        roster = SpecialistRoster({"verifier": _verifier()})
        store.create_workflow(
            Workflow(
                id="wf-1", source="github-issue", task_ref="owner/repo#1",
                repo="owner/repo", base_branch="main",
                source_visibility="public", title="Add a thing",
            )
        )
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="verification",
                title="Verify", state="ready", eligible_roles=("verifier",),
            )
        )
        claims = ClaimsService(
            store=store, claims_store=claims_store, roster=roster,
            max_parallel_read_cards=4, default_lease_seconds=60,
            default_workspace_lease_seconds=600,
        )
        artifacts = ArtifactsService(
            store, artifact_store, board_service, content_store
        )
        coordinator = CoordinatorService(
            store, coordinator_store, board_service
        )
        services = DispatchServices(
            claims, roster, artifacts, coordinator=coordinator
        )
        backend = _FakeBackend(_findings_block(
            '{"category": "nonconformance", "summary": "off-by-one"}'
        ))

        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )

        assert store.get_card("card-1").state == "done"
        remediation = [
            c for c in store.list_cards("wf-1") if c.id != "card-1"
        ]
        assert len(remediation) == 1
        assert remediation[0].kind == "implementation"
        assert "off-by-one" in remediation[0].title

    @pytest.mark.asyncio
    async def test_an_escalation_finding_projects_to_the_task_source(
        self, tmp_path: Path,
    ) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        claims_store = BoardClaimsStore(factory)
        coordinator_store = BoardCoordinatorStore(factory)
        board_service = BoardService(store)
        artifact_store = BoardArtifactStore(factory)
        content_store = BoardArtifactContentStore(tmp_path / "artifacts")
        projections = ProjectionsService(BoardProjectionStore(factory))
        roster = SpecialistRoster({"verifier": _verifier()})
        store.create_workflow(
            Workflow(
                id="wf-1", source="github-issue", task_ref="owner/repo#1",
                repo="owner/repo", base_branch="main",
                source_visibility="public", title="Add a thing",
            )
        )
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="verification",
                title="Verify", state="ready", eligible_roles=("verifier",),
            )
        )
        claims = ClaimsService(
            store=store, claims_store=claims_store, roster=roster,
            max_parallel_read_cards=4, default_lease_seconds=60,
            default_workspace_lease_seconds=600,
        )
        artifacts = ArtifactsService(
            store, artifact_store, board_service, content_store
        )
        coordinator = CoordinatorService(
            store, coordinator_store, board_service
        )
        task_source = _FakeTaskSource()
        services = DispatchServices(
            claims, roster, artifacts, coordinator=coordinator,
            task_sources=_FakeTaskSources({"github-issue": task_source}),
            projections=projections,
        )
        backend = _FakeBackend(_findings_block(
            '{"category": "ambiguity", "summary": "unclear boundary"}'
        ))

        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )

        assert task_source.calls == [
            ("owner/repo#1", "Escalation: unclear boundary")
        ]


class _FakeTaskSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def post_comment(self, ref: str, body: str) -> str:
        self.calls.append((ref, body))
        return "comment-1"


class _FakeTaskSources:
    def __init__(self, sources: dict[str, object]) -> None:
        self.sources = sources
