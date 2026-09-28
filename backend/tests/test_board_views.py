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
from app.models_board_records import (
    BoardEventRecord,
    HandoffArtifact,
    HumanGateRecord,
)
from app.routers.board_views import (
    BoardLookups,
    action_required_count,
    board_events,
    board_snapshot,
    card_summary,
    state_counts,
    visible_workflows,
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


class _StubGates:
    """Minimal stand-in for ``GatesService``'s two read-only facts this
    pure-mapping layer depends on (feature 029 A3/A4)."""

    def __init__(
        self, cap: int = 1, rounds: dict[str, int] | None = None
    ) -> None:
        self.refinement_round_cap = cap
        self._rounds = rounds or {}

    def gate_round(
        self, card: WorkCard, cards: list[WorkCard]
    ) -> int | None:
        del cards
        return self._rounds.get(card.id)


class _StubChildTasks:
    """Minimal stand-in for ``ChildTaskStore.parent_workflow_id`` (feature
    029 A1)."""

    def __init__(self, parents: dict[str, str] | None = None) -> None:
        self._parents = parents or {}

    def parent_workflow_id(self, task_ref: str) -> str | None:
        return self._parents.get(task_ref)


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
    return BoardLookups(
        roster=_ROSTER,
        leases={},
        latest_artifacts={},
        security_review_ids={},
        gates={},
        gate_rounds={},
    )


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
        summary = workflow_summary(
            _WORKFLOW, cards, _StubGates(), _StubChildTasks()
        )
        assert summary.id == "wf-1"
        assert summary.task_label == "owner/repo#1"
        assert summary.title == "Add a thing"
        assert summary.parent_workflow_id is None
        assert summary.status == "active"
        assert summary.state_counts == {"ready": 1}
        assert summary.action_required_count == 0
        assert summary.cap_exhausted is False

    def test_title_falls_back_to_task_label_when_unrecorded(self) -> None:
        workflow = Workflow(**{**_WORKFLOW.__dict__, "title": ""})
        summary = workflow_summary(
            workflow, [], _StubGates(), _StubChildTasks()
        )
        assert summary.title == "owner/repo#1"

    def test_parent_workflow_id_is_set_for_a_decomposed_child(self) -> None:
        summary = workflow_summary(
            _WORKFLOW,
            [],
            _StubGates(),
            _StubChildTasks({"owner/repo#1": "wf-parent"}),
        )
        assert summary.parent_workflow_id == "wf-parent"

    def test_cap_exhausted_when_the_final_round_gate_still_awaits(
        self,
    ) -> None:
        cards = [
            _card(
                "gate-1", kind="refinement_gate", state="awaiting_human"
            )
        ]
        gates = _StubGates(cap=2, rounds={"gate-1": 2})
        summary = workflow_summary(
            _WORKFLOW, cards, gates, _StubChildTasks()
        )
        assert summary.cap_exhausted is True

    def test_not_cap_exhausted_below_the_cap(self) -> None:
        cards = [
            _card(
                "gate-1", kind="refinement_gate", state="awaiting_human"
            )
        ]
        gates = _StubGates(cap=2, rounds={"gate-1": 1})
        summary = workflow_summary(
            _WORKFLOW, cards, gates, _StubChildTasks()
        )
        assert summary.cap_exhausted is False


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
            roster=_ROSTER,
            leases={"card-1": lease},
            latest_artifacts={},
            security_review_ids={},
            gates={},
            gate_rounds={},
        )
        summary = card_summary(_card(state="claimed"), [], lookups)
        assert summary.owner.specialist_id == "developer"
        assert summary.owner.label == "Developer"
        assert summary.lease.attempt == 1

    def test_security_review_id_is_surfaced_for_a_quarantine_card(
        self,
    ) -> None:
        lookups = BoardLookups(
            roster=_ROSTER,
            leases={},
            latest_artifacts={},
            security_review_ids={"card-1": "review-1"},
            gates={},
            gate_rounds={},
        )
        summary = card_summary(
            _card(kind="security_review", state="quarantined"), [], lookups
        )
        assert summary.security_review_id == "review-1"

    def test_security_review_id_is_absent_for_an_ordinary_card(self) -> None:
        summary = card_summary(_card(), [], _empty_lookups())
        assert summary.security_review_id is None

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
            roster=_ROSTER,
            leases={},
            latest_artifacts={"card-1": artifact},
            security_review_ids={},
            gates={},
            gate_rounds={},
        )
        summary = card_summary(_card(), [], lookups)
        assert summary.latest_artifact.id == "artifact-1"
        expected_revision = 2
        assert summary.latest_artifact.revision == expected_revision

    def test_gate_detail_is_surfaced_for_a_gate_card(self) -> None:
        gate = HumanGateRecord(
            id="gate-1",
            card_id="card-1",
            requested_decision="confirm_understanding",
        )
        lookups = BoardLookups(
            roster=_ROSTER,
            leases={},
            latest_artifacts={},
            security_review_ids={},
            gates={"card-1": gate},
            gate_rounds={},
        )
        summary = card_summary(
            _card(kind="understanding_gate"), [], lookups
        )
        assert summary.gate is not None
        assert summary.gate.requested_decision == "confirm_understanding"
        assert summary.gate.decision is None

    def test_gate_detail_carries_a_recorded_decision(self) -> None:
        gate = HumanGateRecord(
            id="gate-1",
            card_id="card-1",
            requested_decision="approve_prd",
            decision="approved",
        )
        lookups = BoardLookups(
            roster=_ROSTER,
            leases={},
            latest_artifacts={},
            security_review_ids={},
            gates={"card-1": gate},
            gate_rounds={},
        )
        summary = card_summary(_card(kind="prd_gate"), [], lookups)
        assert summary.gate.decision == "approved"

    def test_gate_detail_is_absent_for_a_non_gate_card(self) -> None:
        summary = card_summary(_card(), [], _empty_lookups())
        assert summary.gate is None

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


def _quarantine_placeholder(
    workflow_id: str, *, source: str, ticket: str
) -> Workflow:
    return Workflow(
        id=workflow_id,
        source=source,
        task_ref=f"{source}:{ticket}",
        repo="",
        base_branch="",
        source_visibility="private",
        title="Security review",
        state="quarantined",
    )


def _real_workflow(
    workflow_id: str, *, source: str, ticket: str
) -> Workflow:
    return Workflow(
        id=workflow_id,
        source=source,
        task_ref=ticket,
        repo="owner/repo",
        base_branch="main",
        source_visibility="public",
        title="Add a thing",
    )


class TestVisibleWorkflows:
    """A quarantine placeholder must not linger as a duplicate board
    entry once the ticket it hosted also has a real workflow (#45)."""

    def test_a_still_pending_quarantine_stays_visible(self) -> None:
        placeholder = _quarantine_placeholder(
            "wf-quarantine-1", source="github-issue", ticket="owner/repo#7"
        )
        assert visible_workflows([placeholder]) == [placeholder]

    def test_a_resolved_quarantine_collapses_into_its_real_workflow(
        self,
    ) -> None:
        placeholder = _quarantine_placeholder(
            "wf-quarantine-1", source="github-issue", ticket="owner/repo#7"
        )
        real = _real_workflow(
            "wf-1", source="github-issue", ticket="owner/repo#7"
        )
        assert visible_workflows([placeholder, real]) == [real]

    def test_unrelated_workflows_are_unaffected(self) -> None:
        placeholder = _quarantine_placeholder(
            "wf-quarantine-1", source="github-issue", ticket="owner/repo#7"
        )
        other = _real_workflow(
            "wf-2", source="github-issue", ticket="owner/repo#9"
        )
        assert visible_workflows([placeholder, other]) == [
            placeholder,
            other,
        ]


class TestBoardEvents:
    """Board history maps to the narrative feed's safe shape."""

    def test_event_fields_are_carried_through(self) -> None:
        when = datetime.now(timezone.utc)
        events = [
            BoardEventRecord(
                workflow_id="wf-1",
                event_type="card.result_accepted",
                card_id="card-1",
                payload='{"x": 1}',
                created_at=when,
            )
        ]
        out = board_events(events, [_card()], _ROSTER)
        assert len(out) == 1
        assert out[0].event_type == "card.result_accepted"
        assert out[0].card_id == "card-1"
        assert out[0].payload == '{"x": 1}'
        assert out[0].created_at == when

    def test_specialist_is_derived_from_the_cards_eligible_role(
        self,
    ) -> None:
        events = [
            BoardEventRecord(
                workflow_id="wf-1", event_type="card.done", card_id="card-1"
            )
        ]
        out = board_events(events, [_card()], _ROSTER)
        assert out[0].specialist is not None
        assert out[0].specialist.id == "developer"

    def test_workflow_level_event_has_no_specialist(self) -> None:
        events = [
            BoardEventRecord(workflow_id="wf-1", event_type="workflow.created")
        ]
        out = board_events(events, [], _ROSTER)
        assert out[0].card_id is None
        assert out[0].specialist is None

    def test_a_gate_card_with_no_eligible_role_has_no_specialist(
        self,
    ) -> None:
        events = [
            BoardEventRecord(
                workflow_id="wf-1", event_type="card.awaiting_human",
                card_id="gate-1",
            )
        ]
        gate_card = _card(
            "gate-1", kind="understanding_gate", eligible_roles=()
        )
        out = board_events(events, [gate_card], _ROSTER)
        assert out[0].specialist is None

    def test_events_preserve_their_given_order(self) -> None:
        events = [
            BoardEventRecord(workflow_id="wf-1", event_type="first"),
            BoardEventRecord(workflow_id="wf-1", event_type="second"),
        ]
        out = board_events(events, [], _ROSTER)
        assert [e.event_type for e in out] == ["first", "second"]
