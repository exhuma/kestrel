"""Refinement-interview and PRD-gate enforcement tests for
``GatesService`` (feature 026, T078).

Split out of ``test_board_gates.py`` to keep that module under the
repo's 500-line ceiling, mirroring the existing
``test_board_dispatch_workspace.py``/``test_board_scheduling.py`` split.
"""
from __future__ import annotations

from pathlib import Path

from app.models_board import CardRelation, WorkCard
from app.services.board.artifacts import ArtifactDraft
from app.services.board.interview_batch import (
    InterviewBoard,
    maybe_plan_next,
)
from tests.test_board_gates import _service


class TestPrdDecompositionOrdering:
    """T078: when PRD is also required, decomposition must wait for
    prd_gate rather than firing off understanding_gate."""

    def test_decomposition_waits_for_prd_gate_when_both_required(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(
            tmp_path, decomposition_required=True, prd_gate_required=True,
        )
        understanding = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(understanding.id, "approved")

        kinds = {c.kind for c in store.list_cards("wf-1")}
        assert "decomposition" not in kinds
        assert "interview_plan" in kinds


class TestCab1RefinementOrdering:
    """Feature 027: when CAB-1 is also required, refinement must wait for
    cab1_gate rather than firing off understanding_gate directly."""

    def test_refinement_waits_for_cab1_gate_when_required(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(
            tmp_path, prd_gate_required=True, cab1_required=True,
        )
        understanding = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(understanding.id, "approved")

        kinds = {c.kind for c in store.list_cards("wf-1")}
        assert "refinement" not in kinds

    def test_approving_cab1_gate_starts_the_interview_plan(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(
            tmp_path, prd_gate_required=True, cab1_required=True,
        )
        cab1 = service.create_gate(
            "wf-1", kind="cab1_gate", title="Approve strategic fit",
            requested_decision="approve_strategic_fit",
        )

        service.resolve(cab1.id, "approved")

        new_cards = [c for c in store.list_cards("wf-1") if c.id != cab1.id]
        assert [c.kind for c in new_cards] == ["interview_plan"]


class TestRefinementEnforcement:
    """T078, feature 038: approving understanding_gate deterministically
    starts the interview — with the coordinator's plan of who is asked,
    not a fixed list of personas."""

    def test_required_and_not_skipped_starts_the_interview_plan(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, prd_gate_required=True)
        gate = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(gate.id, "approved")

        (plan,) = [c for c in store.list_cards("wf-1") if c.id != gate.id]
        assert (plan.kind, plan.eligible_roles, plan.state) == (
            "interview_plan", ("coordinator",), "ready",
        )

    def test_not_required_creates_nothing(self, tmp_path: Path) -> None:
        service, store = _service(tmp_path, prd_gate_required=False)
        gate = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(gate.id, "approved")

        assert store.list_cards("wf-1") == [store.get_card(gate.id)]

class TestNextInterviewPlan:
    """Feature 038: once every interview of a batch is answered —
    answered or rejected, so the workflow never deadlocks — the
    coordinator plans the next batch."""

    def test_the_last_answer_of_a_batch_plans_the_next(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, prd_gate_required=True)
        plan, gates = _batch(service, store, ("pm", "dba"))

        service.resolve(gates[0].id, "approved", answer="Q: q?\nA: a")
        assert len(_plans(store)) == 1
        service.resolve(gates[1].id, "rejected")

        plans = _plans(store)
        assert [p.title for p in plans] == [
            "Plan interview round 1", "Plan interview round 2",
        ]
        (after,) = [
            r for r in store.list_relations("wf-1")
            if r.card_id == plans[1].id
        ]
        assert after.depends_on_card_id == plan.id

    def test_a_batch_is_planned_after_only_once(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, prd_gate_required=True)
        _plan, gates = _batch(service, store, ("pm",))
        service.resolve(gates[0].id, "approved", answer="Q: q?\nA: a")
        answered = store.get_card(gates[0].id)

        maybe_plan_next(answered, InterviewBoard(
            store, service.get_gate, service._artifacts,
        ))

        assert [c.title for c in _plans(store)] == [
            "Plan interview round 1", "Plan interview round 2",
        ]

    def test_never_duplicates_once_a_prd_card_already_exists(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        gate = service.create_gate(
            "wf-1", kind="refinement_gate", title="interview",
            requested_decision="answer",
        )
        store.create_card(
            WorkCard(
                id="card-existing-prd", workflow_id="wf-1", kind="prd",
                title="Draft PRD", state="ready", eligible_roles=("pm",),
            )
        )

        service.resolve(gate.id, "approved", answer="Q: q?\nA: a")

        prd_cards = [c for c in store.list_cards("wf-1") if c.kind == "prd"]
        assert len(prd_cards) == 1
        assert prd_cards[0].id == "card-existing-prd"


class TestPrdApproval:
    """T078: approving a prd_gate records the approved content on the
    workflow — the durable "approved scope" every later card reads."""

    def test_records_the_gates_target_artifact_content(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        artifact = service._artifacts.store_reference_artifact(
            _draft_artifact("card-1", "the full plan")
        )
        gate = service.create_gate(
            "wf-1", kind="prd_gate", title="Approve PRD",
            requested_decision="approve_prd",
            target_artifact_id=artifact.id,
        )

        service.resolve(gate.id, "approved")

        prd = store.get_workflow("wf-1").approved_prd
        assert prd.plain_text() == "the full plan"

    def test_a_gate_with_no_target_artifact_is_a_no_op(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        gate = service.create_gate(
            "wf-1", kind="prd_gate", title="Approve PRD",
            requested_decision="approve_prd",
        )

        service.resolve(gate.id, "approved")

        assert store.get_workflow("wf-1").approved_prd is None


class TestPrdRedraft:
    """T078: a rejected prd_gate must not deadlock the workflow."""

    def test_rejection_creates_a_fresh_prd_card(self, tmp_path: Path) -> None:
        service, store = _service(tmp_path)
        gate = service.create_gate(
            "wf-1", kind="prd_gate", title="Approve PRD",
            requested_decision="approve_prd",
        )

        service.resolve(gate.id, "rejected", answer="Too vague.")

        new_cards = [c for c in store.list_cards("wf-1") if c.id != gate.id]
        assert len(new_cards) == 1
        assert new_cards[0].kind == "prd"
        assert new_cards[0].state == "ready"
        assert new_cards[0].eligible_roles == ("pm",)

    def test_rejection_is_unconditional_on_the_required_flag(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, prd_gate_required=False)
        gate = service.create_gate(
            "wf-1", kind="prd_gate", title="Approve PRD",
            requested_decision="approve_prd",
        )

        service.resolve(gate.id, "rejected", answer="Too vague.")

        assert any(c.kind == "prd" for c in store.list_cards("wf-1"))


def _draft_artifact(card_id: str, content: str) -> ArtifactDraft:
    return ArtifactDraft(
        producer_card_id=card_id, logical_name="draft", revision=1,
        content=content, trust="agent_output",
    )


def _plans(store) -> list[WorkCard]:
    return [c for c in store.list_cards("wf-1") if c.kind == "interview_plan"]


def _batch(service, store, personas: tuple[str, ...]):
    """A plan and one drafted, gated interview per persona."""
    plan = WorkCard(
        id="plan-1", workflow_id="wf-1", kind="interview_plan",
        title="Plan interview round 1", state="done",
        eligible_roles=("coordinator",),
    )
    store.create_card(plan)
    gates = []
    for persona in personas:
        card = WorkCard(
            id=f"ref-{persona}", workflow_id="wf-1", kind="refinement",
            title=f"{persona} interview questions", state="done",
            eligible_roles=(persona,),
        )
        store.create_card(card)
        store.add_relation(CardRelation(card.id, plan.id))
        target = service._artifacts.store_reference_artifact(
            _questions_artifact(card.id)
        )
        gates.append(service.create_gate(
            "wf-1", kind="refinement_gate", title=f"{persona} interview",
            requested_decision="answer", target_artifact_id=target.id,
        ))
    return plan, gates


def _questions_artifact(card_id: str) -> ArtifactDraft:
    """A minimal ``refinement`` card's output artifact — feature 028's
    round machinery recovers a ``refinement_gate``'s persona via this
    linkage (``ArtifactsService.producer_card_id``), so a gate created
    without one (unlike the real ``route_refinement_result`` flow) is
    invisible to it."""
    return ArtifactDraft(
        producer_card_id=card_id, logical_name="questions", revision=1,
        content='{"questions": ["q?"]}', trust="agent_output",
    )
