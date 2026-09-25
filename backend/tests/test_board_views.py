"""Board DTO serialization tests (feature 026, T053).

Exercises ``app.routers.board_views`` as pure functions — no HTTP layer —
against directly constructed domain objects. Confirms every mapped field
matches board-api.md's shape and that nothing quarantine-adjacent ever
carries raw content (only ``routers/board.py``'s own security-review DTO
does that job, see ``test_board_router.py``).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models_board import (
    CardRelation,
    ClaimLease,
    SpecialistDefinition,
    WorkCard,
    Workflow,
)
from app.models_board_records import HandoffArtifact
from app.routers.board_views import (
    BoardLookups,
    action_required_count,
    board_snapshot,
    card_summary,
    state_counts,
    workflow_summary,
)
from app.services.board.specialists import SpecialistRoster

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)


def _specialist(role_id: str) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id,
        label=role_id.capitalize(),
        purpose="test role",
        allowed_card_types=("analysis",),
        required_abilities=(),
        model_policy="default",
        workspace_permission="read_only",
        retry_limit=1,
        prompt="do the thing",
    )


_ROSTER = SpecialistRoster({"developer": _specialist("developer")})


def _card(card_id: str = "card-1", **overrides: object) -> WorkCard:
    fields: dict[str, object] = {
        "id": card_id,
        "workflow_id": "wf-1",
        "kind": "analysis",
        "title": "Investigate",
        "state": "ready",
        "eligible_roles": ("developer",),
    }
    fields.update(overrides)
    return WorkCard(**fields)


def _empty_lookups() -> BoardLookups:
    return BoardLookups(roster=_ROSTER, leases={}, latest_artifacts={})


class TestStateCounts:
    """State counts tally every card by its exact state string."""

    def test_counts_cards_by_state(self) -> None:
        cards = [
            _card("a", state="ready"),
            _card("b", state="ready"),
            _card("c", state="done"),
        ]
        assert state_counts(cards) == {"ready": 2, "done": 1}


class TestActionRequiredCount:
    """Only states needing operator attention count toward the badge."""

    def test_awaiting_human_and_failed_count(self) -> None:
        cards = [
            _card("a", state="awaiting_human"),
            _card("b", state="failed"),
            _card("c", state="ready"),
        ]
        expected_required = 2
        assert action_required_count(cards) == expected_required


class TestWorkflowSummary:
    """The collection-listing row surfaces label, status, and counts."""

    def test_summary_fields(self) -> None:
        cards = [_card(state="ready")]
        summary = workflow_summary(_WORKFLOW, cards)
        assert summary.id == "wf-1"
        assert summary.task_label == "owner/repo#1"
        assert summary.status == "active"
        assert summary.state_counts == {"ready": 1}
        assert summary.action_required_count == 0


class TestCardSummary:
    """A card's summary reflects role labels, ownership, and actions."""

    def test_eligible_roles_include_the_roster_label(self) -> None:
        summary = card_summary(_card(), [], _empty_lookups())
        assert summary.eligible_roles[0].id == "developer"
        assert summary.eligible_roles[0].label == "Developer"

    def test_unclaimed_card_has_no_owner_or_lease(self) -> None:
        summary = card_summary(_card(), [], _empty_lookups())
        assert summary.owner is None
        assert summary.lease is None

    def test_claimed_card_reports_owner_and_lease(self) -> None:
        lease = ClaimLease(
            card_id="card-1",
            attempt_sequence=1,
            specialist_id="developer",
            expires_at=datetime.now(timezone.utc),
        )
        lookups = BoardLookups(
            roster=_ROSTER, leases={"card-1": lease}, latest_artifacts={}
        )
        summary = card_summary(_card(state="claimed"), [], lookups)
        assert summary.owner.specialist_id == "developer"
        assert summary.owner.label == "Developer"
        assert summary.lease.attempt == 1

    def test_dependency_count_only_counts_dependency_kind_relations(
        self,
    ) -> None:
        relations = [
            CardRelation("card-1", "card-0", kind="dependency"),
            CardRelation("card-1", "card-2", kind="reconciliation"),
        ]
        summary = card_summary(_card(), relations, _empty_lookups())
        assert summary.dependency_count == 1

    def test_latest_artifact_is_surfaced_as_a_safe_reference(self) -> None:
        artifact = HandoffArtifact(
            id="artifact-1",
            producer_card_id="card-1",
            logical_name="report",
            revision=2,
            content_ref="board-artifact://abc",
            content_hash="abc",
            trust="agent_output",
        )
        lookups = BoardLookups(
            roster=_ROSTER, leases={}, latest_artifacts={"card-1": artifact}
        )
        summary = card_summary(_card(), [], lookups)
        assert summary.latest_artifact.id == "artifact-1"
        expected_revision = 2
        assert summary.latest_artifact.revision == expected_revision

    def test_allowed_actions_reflect_card_state(self) -> None:
        summary = card_summary(_card(state="failed"), [], _empty_lookups())
        assert "retry" in summary.allowed_actions


class TestBoardSnapshot:
    """The full snapshot bundles cards, relations, and revision together."""

    def test_snapshot_carries_the_workflow_revision(self) -> None:
        expected_revision = 7
        workflow = Workflow(
            **{**_WORKFLOW.__dict__, "revision": expected_revision}
        )
        snapshot = board_snapshot(workflow, [_card()], [], _empty_lookups())
        assert snapshot.revision == expected_revision
        assert len(snapshot.cards) == 1

    def test_snapshot_includes_relationships(self) -> None:
        relations = [CardRelation("card-1", "card-0", kind="dependency")]
        snapshot = board_snapshot(
            _WORKFLOW, [_card()], relations, _empty_lookups()
        )
        assert len(snapshot.relationships) == 1
        assert snapshot.relationships[0].depends_on_card_id == "card-0"
