"""Tests for materialising an approved CAB-2 decomposition into cards
(feature 031, US1), and for its tasks waiting to be handed over (#99)."""
from __future__ import annotations

import json
from pathlib import Path

from app.document_formats.markdown import render_markdown
from app.models_board import WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.gates import GateRequirements, GatesService
from app.services.board.materialise import (
    CLASSIFICATION_LOGICAL_NAME,
    TASK_SPEC_LOGICAL_NAME,
    MaterialiseTarget,
    materialise_decomposition,
    task_context,
)
from app.services.board.service import BoardService
from tests.test_board_decomposition import _setup

_ESTIMATE = {
    "size": "M", "confidence": "low", "man_hours": 6,
    "agent_tokens": 400000, "review_hours": 1.5,
    "risks": ["schema migration"], "rationale": "one table",
}


def _task(node: str, title: str, **extra: object) -> dict:
    task: dict = {
        "task_node_id": node, "title": title, "body": f"{title} body",
        "classification": "coding", "prerequisites": [],
    }
    task.update(extra)
    return task


class _Board:
    """A workflow with an approved-ready CAB-2 gate."""

    def __init__(self, tmp_path: Path, *, handover: bool = False) -> None:
        store, _coordinator, gates, artifacts, card, gate_store = _setup(
            tmp_path
        )
        self.store: BoardStore = store
        self.gates: GatesService = gates
        if handover:
            self.gates = GatesService(
                store, gate_store, BoardService(store), artifacts,
                required=GateRequirements(handover=lambda _wid: True),
            )
        self.artifacts: ArtifactsService = artifacts
        self.producer: WorkCard = card

    def approve(self, *tasks: dict, revision: int = 1) -> WorkCard:
        """Open a CAB-2 gate targeting *tasks* and approve it."""
        target = self.artifacts.store_reference_artifact(
            ArtifactDraft(
                producer_card_id=self.producer.id,
                logical_name="cab2_proposal",
                revision=revision,
                content=json.dumps({"summary": "s", "tasks": list(tasks)}),
                trust="agent_output",
            )
        )
        gate = self.gates.create_gate(
            "wf-1", kind="decomposition_gate", title="CAB-2",
            requested_decision="approve_decomposition",
            target_artifact_id=target.id,
        )
        return self.gates.resolve(gate.id, "approved")

    def tagged(self) -> list[WorkCard]:
        return [c for c in self.store.list_cards("wf-1") if c.task_node_id]

    def one(self, kind: str, node: str) -> WorkCard:
        (card,) = [
            c for c in self.tagged()
            if c.kind == kind and c.task_node_id == node
        ]
        return card

    def depends_on(self, card: WorkCard) -> set[str]:
        return {
            r.depends_on_card_id for r in self.store.list_relations("wf-1")
            if r.card_id == card.id
        }


def test_a_coding_task_gets_implementation_and_verification(
    tmp_path: Path,
) -> None:
    """Ensure each coding task becomes coder work plus its verification."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Audit table"))

    impl = board.one("implementation", "t1")
    ver = board.one("verification", "t1")
    assert (impl.title, impl.state) == ("Audit table", "ready")
    assert impl.eligible_roles == ("coder",)
    assert impl.workspace_permission == "write"
    assert ver.title == "Verify: Audit table"
    assert ver.state == "waiting_dependency"
    assert ver.eligible_roles == ("verifier",)
    assert ver.workspace_permission == "read_only"
    assert board.depends_on(ver) == {impl.id}


def test_a_task_planned_for_a_person_is_still_one_task_for_the_board(
    tmp_path: Path,
) -> None:
    """Ensure the classification is information only (#99): every task
    gets implementation and verification, and keeps how it was planned."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Legal sign-off", classification="manual"))

    head = board.one("implementation", "t1")
    assert board.one("verification", "t1").state == "waiting_dependency"
    assert board.artifacts.latest_content_for_card(
        head.id, CLASSIFICATION_LOGICAL_NAME
    ) == "manual"
    spec = render_markdown(board.artifacts.latest_document_for_card(
        head.id, TASK_SPEC_LOGICAL_NAME
    ))
    assert "Planned for a person" in spec


def test_on_a_hand_over_source_a_task_waits_to_be_handed_over(
    tmp_path: Path,
) -> None:
    """Ensure nothing starts at CAB-2 when the source can say who has a
    work item (#99): every head card waits, prerequisites or not."""
    board = _Board(tmp_path, handover=True)
    board.approve(
        _task("t1", "Schema"),
        _task("t2", "Client", prerequisites=["t1"]),
    )

    for node in ("t1", "t2"):
        head = board.one("implementation", node)
        verification = board.one("verification", node)
        assert head.state == "waiting_handover"
        assert verification.state == "waiting_dependency"
        assert board.depends_on(verification) == {head.id}
    assert board.depends_on(board.one("implementation", "t2")) == {
        board.one("implementation", "t1").id
    }


def test_without_hand_over_a_task_starts_at_once(tmp_path: Path) -> None:
    """Ensure a source that cannot say who has an item starts its tasks
    as before: ready, or waiting on a prerequisite."""
    board = _Board(tmp_path)
    board.approve(
        _task("t1", "Schema"),
        _task("t2", "Client", prerequisites=["t1"]),
    )

    assert board.one("implementation", "t1").state == "ready"
    assert board.one("implementation", "t2").state == "waiting_dependency"


def test_prerequisites_become_dependencies_between_head_cards(
    tmp_path: Path,
) -> None:
    """Ensure a task waits on the head cards of its prerequisites,
    whoever the plan expects to do them."""
    board = _Board(tmp_path)
    board.approve(
        _task("t1", "Schema"),
        _task("t2", "API key", classification="manual"),
        _task("t3", "Client", prerequisites=["t1", "t2"]),
    )

    client = board.one("implementation", "t3")
    assert client.state == "waiting_dependency"
    assert board.depends_on(client) == {
        board.one("implementation", "t1").id,
        board.one("implementation", "t2").id,
    }


def test_task_spec_carries_the_approved_text_and_estimate(
    tmp_path: Path,
) -> None:
    """Ensure the head card holds what CAB-2 approved, as approved."""
    board = _Board(tmp_path)
    board.approve(
        _task("t1", "Schema"),
        _task("t2", "Client", prerequisites=["t1"], estimate=_ESTIMATE),
    )

    head = board.one("implementation", "t2")
    spec = render_markdown(board.artifacts.latest_document_for_card(
        head.id, TASK_SPEC_LOGICAL_NAME
    ))
    assert spec.startswith("# Client\n")
    assert "Prerequisites: Schema" in spec
    assert "Client body" in spec
    assert "## Estimate (agent, unverified)" in spec
    assert "Risks: schema migration" in spec
    artifacts = board.artifacts._artifact_store.list_for_card(head.id)
    assert {a.trust for a in artifacts} == {"operator_approved"}


def test_no_task_card_is_created_twice(tmp_path: Path) -> None:
    """Ensure applying the same approval again adds nothing."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Schema"))
    before = {c.id for c in board.tagged()}

    materialise_decomposition(
        "wf-1",
        json.dumps({"summary": "s", "tasks": [_task("t1", "Schema")]}),
        MaterialiseTarget(board.store, board.artifacts),
    )

    assert {c.id for c in board.tagged()} == before


def test_a_legacy_candidate_gets_positional_ids_as_coding(
    tmp_path: Path,
) -> None:
    """Ensure a gate approved before features 030/031 still materialises."""
    board = _Board(tmp_path)
    board.approve(
        {"title": "Old one", "body": "b"}, {"title": "Old two", "body": "b"}
    )

    assert {c.task_node_id for c in board.tagged()} == {"t1", "t2"}
    assert {c.kind for c in board.tagged()} == {
        "implementation", "verification"
    }


def test_an_unknown_prerequisite_is_dropped_not_waited_on(
    tmp_path: Path,
) -> None:
    """Ensure a legacy dangling prerequisite never strands a task."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Schema", prerequisites=["gone"]))

    assert board.one("implementation", "t1").state == "ready"


def test_every_card_on_a_task_works_from_its_approved_text(
    tmp_path: Path,
) -> None:
    """Ensure verification and later remediation cards see the task too."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Schema"))
    remediation = WorkCard(
        id="card-fix", workflow_id="wf-1", kind="implementation",
        title="Remediate: x", state="ready", task_node_id="t1",
    )
    board.store.create_card(remediation)
    cards = board.store.list_cards("wf-1")

    for card in (board.one("verification", "t1"), remediation):
        context = task_context(card, cards, board.artifacts)
        assert context.startswith("Approved task:\n# Schema\n")


def test_a_card_with_no_task_gets_no_task_context(tmp_path: Path) -> None:
    board = _Board(tmp_path)

    assert task_context(board.producer, [], board.artifacts) == ""


def test_the_estimate_reads_as_it_did_on_a_child_ticket(
    tmp_path: Path,
) -> None:
    """Ensure the estimate format feature 030 published is kept."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Schema", estimate=_ESTIMATE))

    spec = render_markdown(board.artifacts.latest_document_for_card(
        board.one("implementation", "t1").id, TASK_SPEC_LOGICAL_NAME
    ))
    assert (
        "Size M · confidence low · ~6.0 man-hours · "
        "~400,000 agent tokens · ~1.5 review hours"
    ) in spec
    assert "Rationale: one table" in spec


def test_a_replanned_request_gets_its_own_task_ids(tmp_path: Path) -> None:
    """Ensure a plan approved after the PRD changed creates its work,
    with ids that cannot be confused with the first plan's."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "First plan"))

    board.approve(_task("t1", "Second plan"), revision=2)

    titles = {
        c.task_node_id: c.title for c in board.store.list_cards("wf-1")
        if c.kind == "implementation"
    }
    assert titles == {"t1": "First plan", "plan2-t1": "Second plan"}
