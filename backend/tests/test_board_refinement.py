"""Tests for refinement-interview and PRD-draft parsing and routing
(feature 026, T078).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models_board import WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_gate_store import BoardGateStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.gates import GatesService
from app.services.board.refinement import (
    RefinementResultError,
    gather_refinement_context,
    parse_prd_draft,
    parse_refinement_questions,
    parse_refinement_round,
    route_prd_result,
    route_refinement_result,
    route_strategic_interview_result,
)
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_DEFAULT_CAB1_QUESTION_CAP = 3

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add a thing",
)


def _refinement_block(*questions: str) -> str:
    q = ",".join(f'"{q}"' for q in questions)
    return (
        '<REFINEMENT_QUESTIONS>{"questions": [' + q + "]}"
        "</REFINEMENT_QUESTIONS>"
    )


class TestParseRefinementQuestions:
    def test_parses_a_valid_block(self) -> None:
        text = _refinement_block("What is the deadline?", "Who approves?")
        assert parse_refinement_questions(text) == [
            "What is the deadline?", "Who approves?",
        ]

    def test_missing_tag_raises(self) -> None:
        with pytest.raises(RefinementResultError):
            parse_refinement_questions("no tag here")

    def test_empty_questions_raises(self) -> None:
        with pytest.raises(RefinementResultError):
            parse_refinement_questions(_refinement_block())

    def test_malformed_json_raises(self) -> None:
        text = "<REFINEMENT_QUESTIONS>{not json}</REFINEMENT_QUESTIONS>"
        with pytest.raises(RefinementResultError):
            parse_refinement_questions(text)

    def test_non_string_question_raises(self) -> None:
        text = (
            '<REFINEMENT_QUESTIONS>{"questions": [1]}</REFINEMENT_QUESTIONS>'
        )
        with pytest.raises(RefinementResultError):
            parse_refinement_questions(text)


class TestParseRefinementRound:
    """Feature 028: an empty ``questions`` list is only valid alongside
    ``"satisfied": true``."""

    def test_satisfied_with_no_questions_parses(self) -> None:
        text = (
            '<REFINEMENT_QUESTIONS>{"questions": [], "satisfied": true}'
            "</REFINEMENT_QUESTIONS>"
        )
        result = parse_refinement_round(text)
        assert result.questions == []
        assert result.satisfied is True

    def test_satisfied_with_questions_still_parses(self) -> None:
        text = (
            '<REFINEMENT_QUESTIONS>{"questions": ["One more thing?"], '
            '"satisfied": true}</REFINEMENT_QUESTIONS>'
        )
        result = parse_refinement_round(text)
        assert result.questions == ["One more thing?"]
        assert result.satisfied is True

    def test_no_satisfied_key_defaults_to_false_and_requires_questions(
        self,
    ) -> None:
        text = _refinement_block()
        with pytest.raises(RefinementResultError):
            parse_refinement_round(text)

    def test_unsatisfied_empty_questions_still_raises(self) -> None:
        text = (
            '<REFINEMENT_QUESTIONS>{"questions": [], "satisfied": false}'
            "</REFINEMENT_QUESTIONS>"
        )
        with pytest.raises(RefinementResultError):
            parse_refinement_round(text)

    def test_ordinary_questions_are_unaffected(self) -> None:
        result = parse_refinement_round(
            _refinement_block("What is the deadline?")
        )
        assert result.questions == ["What is the deadline?"]
        assert result.satisfied is False


class TestParsePrdDraft:
    def test_parses_a_valid_block(self) -> None:
        assert parse_prd_draft("<PRD>the plan</PRD>") == "the plan"

    def test_missing_tag_raises(self) -> None:
        with pytest.raises(RefinementResultError):
            parse_prd_draft("no tag here")

    def test_empty_block_raises(self) -> None:
        with pytest.raises(RefinementResultError):
            parse_prd_draft("<PRD>   </PRD>")


def _setup(tmp_path: Path):
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    coordinator_store = BoardCoordinatorStore(factory)
    gate_store = BoardGateStore(factory)
    artifact_store = BoardArtifactStore(factory)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    board_service = BoardService(store)
    coordinator = CoordinatorService(store, coordinator_store, board_service)
    artifacts = ArtifactsService(
        store, artifact_store, board_service, content_store
    )
    gates = GatesService(store, gate_store, board_service, artifacts)
    store.create_workflow(_WORKFLOW)
    return store, coordinator, gates, artifacts


class TestRouteRefinementResult:
    def test_creates_a_refinement_gate_named_for_the_persona(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="refinement",
            title="requester interview questions", state="review",
            eligible_roles=("requester",),
        )
        store.create_card(card)

        route_refinement_result(
            _refinement_block("What's the deadline?"), card, coordinator,
            gates, artifacts,
        )

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "refinement_gate"
        assert new_cards[0].state == "awaiting_human"
        assert "requester interview" in new_cards[0].title

    def test_unparseable_result_escalates_fail_closed(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="refinement",
            title="pm interview questions", state="review",
            eligible_roles=("pm",),
        )
        store.create_card(card)

        route_refinement_result(
            "no structured block", card, coordinator, gates, artifacts,
        )

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"

    def test_satisfied_with_no_questions_completes_with_no_gate(
        self, tmp_path: Path
    ) -> None:
        """Feature 028: a persona declaring itself satisfied is done
        directly — no gate, nothing left for the operator to answer."""
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="refinement",
            title="uiux interview questions", state="review",
            eligible_roles=("uiux",),
        )
        store.create_card(card)
        satisfied_block = (
            '<REFINEMENT_QUESTIONS>{"questions": [], "satisfied": true}'
            "</REFINEMENT_QUESTIONS>"
        )

        route_refinement_result(
            satisfied_block, card, coordinator, gates, artifacts,
        )

        assert store.get_card("card-1").state == "done"
        assert not any(
            c.kind == "refinement_gate" for c in store.list_cards("wf-1")
        )
        # This is the only persona in the test, so satisfying it directly
        # (no gate) still triggers the same "every persona done -> start
        # PRD" check an answered gate would (see GatesService.
        # mark_refinement_satisfied).
        assert any(c.kind == "prd" for c in store.list_cards("wf-1"))


class TestRouteStrategicInterviewResult:
    def test_creates_a_strategic_interview_gate(self, tmp_path: Path) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="strategic_interview",
            title="Strategic fit interview", state="review",
            eligible_roles=("requester",),
        )
        store.create_card(card)

        route_strategic_interview_result(
            _refinement_block("Why does this matter?"), card, coordinator,
            gates, artifacts,
        )

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "strategic_interview_gate"
        assert new_cards[0].state == "awaiting_human"

    def test_truncates_to_the_configured_question_cap(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="strategic_interview",
            title="Strategic fit interview", state="review",
            eligible_roles=("requester",),
        )
        store.create_card(card)
        assert gates.cab1_interview_max_questions == _DEFAULT_CAB1_QUESTION_CAP

        route_strategic_interview_result(
            _refinement_block("Q1?", "Q2?", "Q3?", "Q4?", "Q5?"), card,
            coordinator, gates, artifacts,
        )

        gate_card = next(
            c for c in store.list_cards("wf-1") if c.id != "card-1"
        )
        assert f"{_DEFAULT_CAB1_QUESTION_CAP} question" in gate_card.title
        record = gates.get_gate(gate_card.id)
        content = json.loads(artifacts.read_content(record.target_artifact_id))
        assert content["questions"] == ["Q1?", "Q2?", "Q3?"]

    def test_unparseable_result_escalates_fail_closed(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="strategic_interview",
            title="Strategic fit interview", state="review",
            eligible_roles=("requester",),
        )
        store.create_card(card)

        route_strategic_interview_result(
            "no structured block", card, coordinator, gates, artifacts,
        )

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"


class TestRoutePrdResult:
    def test_creates_a_prd_gate(self, tmp_path: Path) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="prd",
            title="Draft PRD", state="review", eligible_roles=("pm",),
        )
        store.create_card(card)

        route_prd_result(
            "<PRD>the full plan</PRD>", card, coordinator, gates, artifacts,
        )

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "prd_gate"
        assert new_cards[0].state == "awaiting_human"

    def test_unparseable_result_escalates_fail_closed(
        self, tmp_path: Path
    ) -> None:
        store, coordinator, gates, artifacts = _setup(tmp_path)
        card = WorkCard(
            id="card-1", workflow_id="wf-1", kind="prd",
            title="Draft PRD", state="review", eligible_roles=("pm",),
        )
        store.create_card(card)

        route_prd_result("no tag here", card, coordinator, gates, artifacts)

        new_cards = [c for c in store.list_cards("wf-1") if c.id != "card-1"]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "coordinator_review"


class TestGatherRefinementContext:
    def test_gathers_every_answered_interview(self, tmp_path: Path) -> None:
        store, _coordinator, gates, artifacts = _setup(tmp_path)
        gate = gates.create_gate(
            "wf-1", kind="refinement_gate", title="requester interview",
            requested_decision="answer",
        )
        gates.resolve(gate.id, "approved", answer="Ship by Friday.")

        context = gather_refinement_context("wf-1", store, artifacts)

        assert "requester interview" in context
        assert "Ship by Friday." in context

    def test_includes_prior_prd_rejection_feedback(
        self, tmp_path: Path
    ) -> None:
        store, _coordinator, gates, artifacts = _setup(tmp_path)
        prd_gate = gates.create_gate(
            "wf-1", kind="prd_gate", title="Approve PRD",
            requested_decision="approve_prd",
        )
        gates.resolve(prd_gate.id, "rejected", answer="Too vague on scope.")

        context = gather_refinement_context("wf-1", store, artifacts)

        assert "Prior rejection feedback" in context
        assert "Too vague on scope." in context

    def test_empty_when_nothing_answered_yet(self, tmp_path: Path) -> None:
        store, _coordinator, _gates, artifacts = _setup(tmp_path)

        assert gather_refinement_context("wf-1", store, artifacts) == ""
