"""Refinement-interview and PRD-gate enforcement tests for
``GatesService`` (feature 026, T078).

Split out of ``test_board_gates.py`` to keep that module under the
repo's 500-line ceiling, mirroring the existing
``test_board_dispatch_workspace.py``/``test_board_scheduling.py`` split.
"""
from __future__ import annotations

from pathlib import Path

from app.models_board import WorkCard, Workflow
from app.services.board.artifacts import ArtifactDraft
from tests.test_board_gates import _service

_INTERVIEW_PERSONA_COUNT = 3


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
        assert "refinement" in kinds


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

    def test_approving_cab1_gate_creates_three_interview_cards(
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
        assert len(new_cards) == _INTERVIEW_PERSONA_COUNT
        assert {c.kind for c in new_cards} == {"refinement"}


class TestRefinementEnforcement:
    """T078: approving understanding_gate can deterministically create the
    three persona interview cards, independent of the coordinator's own
    judgment."""

    def test_required_and_not_skipped_creates_three_interview_cards(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, prd_gate_required=True)
        gate = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(gate.id, "approved")

        new_cards = [c for c in store.list_cards("wf-1") if c.id != gate.id]
        assert len(new_cards) == _INTERVIEW_PERSONA_COUNT
        assert {c.kind for c in new_cards} == {"refinement"}
        assert {c.eligible_roles for c in new_cards} == {
            ("requester",), ("pm",), ("uiux",),
        }
        assert all(c.state == "ready" for c in new_cards)

    def test_not_required_creates_nothing(self, tmp_path: Path) -> None:
        service, store = _service(tmp_path, prd_gate_required=False)
        gate = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(gate.id, "approved")

        assert store.list_cards("wf-1") == [store.get_card(gate.id)]

    def test_a_skip_decomposition_workflow_is_exempt_even_when_required(
        self, tmp_path: Path
    ) -> None:
        subtask_workflow = Workflow(
            id="wf-2", source="github-issue", task_ref="owner/repo#2",
            repo="owner/repo", base_branch="main", source_visibility="public",
            title="A published child", skip_decomposition=True,
        )
        service, store = _service(
            tmp_path, prd_gate_required=True, workflow=subtask_workflow,
        )
        gate = service.create_gate(
            "wf-2", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )

        service.resolve(gate.id, "approved")

        assert store.list_cards("wf-2") == [store.get_card(gate.id)]


class TestPrdDraftTrigger:
    """T078: once every interview is terminal, pm's PRD-drafting card
    appears — regardless of whether each interview was answered or
    rejected, so the workflow never deadlocks on one persona."""

    def test_appears_once_all_three_interviews_are_answered(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path, prd_gate_required=True)
        understanding = service.create_gate(
            "wf-1", kind="understanding_gate", title="Confirm understanding",
            requested_decision="Approve?",
        )
        service.resolve(understanding.id, "approved")
        interviews = [
            c for c in store.list_cards("wf-1") if c.kind == "refinement"
        ]
        gates = [
            service.create_gate(
                "wf-1", kind="refinement_gate", title=f"{c.eligible_roles[0]}",
                requested_decision="answer",
                target_artifact_id=service._artifacts.store_reference_artifact(
                    _questions_artifact(c.id)
                ).id,
            )
            for c in interviews
        ]

        service.resolve(gates[0].id, "approved", answer="a")
        assert not any(c.kind == "prd" for c in store.list_cards("wf-1"))
        service.resolve(gates[1].id, "approved", answer="b")
        assert not any(c.kind == "prd" for c in store.list_cards("wf-1"))
        service.resolve(gates[2].id, "approved", answer="c")

        prd_cards = [c for c in store.list_cards("wf-1") if c.kind == "prd"]
        assert len(prd_cards) == 1
        assert prd_cards[0].eligible_roles == ("pm",)
        assert prd_cards[0].state == "ready"

    def test_a_rejected_interview_still_counts_as_terminal(
        self, tmp_path: Path
    ) -> None:
        service, store = _service(tmp_path)
        gates = [
            service.create_gate(
                "wf-1", kind="refinement_gate", title=f"interview {i}",
                requested_decision="answer",
            )
            for i in range(_INTERVIEW_PERSONA_COUNT)
        ]

        service.resolve(gates[0].id, "rejected")
        service.resolve(gates[1].id, "approved", answer="a")
        service.resolve(gates[2].id, "approved", answer="c")

        prd_cards = [c for c in store.list_cards("wf-1") if c.kind == "prd"]
        assert len(prd_cards) == 1

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

        service.resolve(gate.id, "approved", answer="a")

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

        assert store.get_workflow("wf-1").approved_prd == "the full plan"

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

        service.resolve(gate.id, "rejected")

        assert any(c.kind == "prd" for c in store.list_cards("wf-1"))


def _draft_artifact(card_id: str, content: str) -> ArtifactDraft:
    return ArtifactDraft(
        producer_card_id=card_id, logical_name="draft", revision=1,
        content=content, trust="agent_output",
    )


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
