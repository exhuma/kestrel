"""Eligibility, parallel read-only dispatch, one-writer, no-ready-work, and
dependency-wait tests for ``ClaimsService`` (feature 026, T029).

``ClaimsService`` decides which ready card a specialist may attempt to
claim (role + card-kind eligibility, read-only capacity); the underlying
atomic claim/write-lease mechanics are covered by ``test_board_claims.py``.
"""
from __future__ import annotations

from pathlib import Path

from app.models_board import SpecialistDefinition, WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board.claims import (
    ClaimsService,
    NoEligibleCardError,
    ReadCapacityExceededError,
)
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


def _specialist(
    role_id: str, *, allowed_card_types: tuple[str, ...]
) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id,
        label=role_id,
        purpose="test role",
        allowed_card_types=allowed_card_types,
        required_abilities=(),
        model_policy="default",
        workspace_permission="write" if "implementation" in allowed_card_types
        else "read_only",
        retry_limit=1,
        prompt="do the thing",
    )


_ROSTER = SpecialistRoster(
    {
        "developer": _specialist("developer", allowed_card_types=("analysis",)),
        "architect": _specialist("architect", allowed_card_types=("analysis",)),
        "coder": _specialist(
            "coder", allowed_card_types=("implementation",)
        ),
    }
)




def _service(
    tmp_path: Path, *, max_parallel_read_cards: int = 4
) -> tuple[ClaimsService, BoardStore]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    claims_store = BoardClaimsStore(factory)
    store.create_workflow(_WORKFLOW)
    service = ClaimsService(
        store=store,
        claims_store=claims_store,
        roster=_ROSTER,
        max_parallel_read_cards=max_parallel_read_cards,
        default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )
    return service, store


def _card(
    card_id: str,
    *,
    kind: str = "analysis",
    eligible_roles: tuple[str, ...] = ("developer",),
    state: str = "ready",
    workspace_permission: str = "none",
) -> WorkCard:
    return WorkCard(
        id=card_id,
        workflow_id="wf-1",
        kind=kind,
        title=card_id,
        state=state,
        eligible_roles=eligible_roles,
        workspace_permission=workspace_permission,
    )


class TestEligibility:
    """A specialist can only claim a card matching its role and card kind."""

    def test_claims_a_ready_card_matching_role_and_kind(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        store.create_card(_card("card-1"))

        claimed = service.claim_next_ready_card("wf-1", "developer")

        assert claimed.id == "card-1"
        assert claimed.state == "claimed"

    def test_card_not_naming_the_role_is_not_eligible(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        store.create_card(_card("card-1", eligible_roles=("architect",)))

        try:
            service.claim_next_ready_card("wf-1", "developer")
        except NoEligibleCardError:
            pass
        else:
            raise AssertionError("must not claim ineligible card")

    def test_card_kind_not_in_specialists_allowed_types_is_not_eligible(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        store.create_card(
            _card(
                "card-1",
                kind="implementation",
                eligible_roles=("developer",),
            )
        )

        try:
            service.claim_next_ready_card("wf-1", "developer")
        except NoEligibleCardError:
            pass
        else:
            raise AssertionError("must not claim wrong-kind card")

    def test_unknown_specialist_raises(self, tmp_path: Path) -> None:
        service, store = _service(tmp_path)
        store.create_card(_card("card-1"))

        try:
            service.claim_next_ready_card("wf-1", "ghost")
        except NoEligibleCardError:
            pass
        else:
            raise AssertionError("must not claim for unknown specialist")


class TestNoReadyWork:
    """No eligible card means no claim, without raising anything else."""

    def test_no_cards_at_all(self, tmp_path: Path) -> None:
        service, _store = _service(tmp_path)

        try:
            service.claim_next_ready_card("wf-1", "developer")
        except NoEligibleCardError:
            pass
        else:
            raise AssertionError("must not run")


class TestDependencyWait:
    """A waiting_dependency card is not claimable."""

    def test_waiting_dependency_card_is_not_eligible(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        store.create_card(_card("card-1", state="waiting_dependency"))

        try:
            service.claim_next_ready_card("wf-1", "developer")
        except NoEligibleCardError:
            pass
        else:
            raise AssertionError("must not claim a waiting card")


class TestParallelReadOnlyDispatch:
    """Independent read-only cards may be claimed up to configured capacity."""

    def test_two_read_only_cards_can_both_be_claimed(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, max_parallel_read_cards=2)
        store.create_card(_card("card-1", eligible_roles=("developer",)))
        store.create_card(_card("card-2", eligible_roles=("architect",)))

        first = service.claim_next_ready_card("wf-1", "developer")
        second = service.claim_next_ready_card("wf-1", "architect")

        assert first.state == "claimed"
        assert second.state == "claimed"

    def test_capacity_exhausted_rejects_a_further_read_only_claim(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, max_parallel_read_cards=1)
        store.create_card(_card("card-1", eligible_roles=("developer",)))
        store.create_card(_card("card-2", eligible_roles=("architect",)))

        service.claim_next_ready_card("wf-1", "developer")

        try:
            service.claim_next_ready_card("wf-1", "architect")
        except ReadCapacityExceededError:
            pass
        else:
            raise AssertionError("must not exceed read capacity")


class TestOneWriter:
    """Only one write-capable card can hold a repository's workspace lease."""

    def test_second_write_claim_for_the_same_repo_fails(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        store.create_card(
            _card(
                "card-1",
                kind="implementation",
                eligible_roles=("coder",),
                workspace_permission="write",
            )
        )
        store.create_card(
            _card(
                "card-2",
                kind="implementation",
                eligible_roles=("coder",),
                workspace_permission="write",
            )
        )

        first = service.claim_next_ready_card("wf-1", "coder")
        assert first.state == "claimed"

        try:
            service.claim_next_ready_card("wf-1", "coder")
        except NoEligibleCardError:
            pass
        else:
            raise AssertionError("must not claim a second writer")
