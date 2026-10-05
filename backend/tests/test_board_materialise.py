"""Tests for materialising an approved CAB-2 decomposition into cards
(feature 031, US1)."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.document_formats.markdown import render_markdown
from app.models_board import WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board import bootstrap
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.candidate import load_candidate
from app.services.board.claims import ClaimsService, NoEligibleCardError
from app.services.board.gates import GatesService
from app.services.board.materialise import (
    TASK_SPEC_LOGICAL_NAME,
    render_breakdown,
    task_context,
)
from app.services.board.specialists import SpecialistRoster
from tests.board_test_support import board_session_factory
from tests.test_board_decomposition import _setup
from tests.test_board_delivery import _verifier

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

    def __init__(self, tmp_path: Path) -> None:
        store, _coordinator, gates, artifacts, card, _ = _setup(tmp_path)
        self.store: BoardStore = store
        self.gates: GatesService = gates
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


def test_a_manual_task_gets_one_operator_card(tmp_path: Path) -> None:
    """Ensure a manual task is the operator's move, claimable by nobody."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Legal sign-off", classification="manual"))

    (manual,) = board.tagged()
    assert manual.kind == "manual_task"
    assert manual.state == "awaiting_human"
    assert manual.eligible_roles == ()


def test_prerequisites_become_dependencies_between_head_cards(
    tmp_path: Path,
) -> None:
    """Ensure a coding task waits on a coding and a manual prerequisite."""
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
        board.one("manual_task", "t2").id,
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
    (artifact,) = board.artifacts._artifact_store.list_for_card(head.id)
    assert artifact.trust == "operator_approved"


def test_no_task_card_is_created_twice(tmp_path: Path) -> None:
    """Ensure a second approval of the same breakdown adds nothing."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Schema"))
    before = {c.id for c in board.tagged()}

    board.approve(_task("t1", "Schema"), revision=2)

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


def test_an_all_manual_breakdown_creates_no_agent_work(
    tmp_path: Path,
) -> None:
    """Ensure nothing is implemented, verified or delivered (FR-015)."""
    board = _Board(tmp_path)
    board.approve(
        _task("t1", "Call vendor", classification="manual"),
        _task("t2", "Announce", classification="manual"),
    )

    assert {c.kind for c in board.tagged()} == {"manual_task"}


def test_the_breakdown_comment_lists_every_task_and_its_kind() -> None:
    """Ensure the one ticket comment says what was approved (FR-006)."""
    candidate = load_candidate(
        json.dumps({"tasks": [
            _task("t1", "Schema"),
            _task("t2", "API key", classification="manual"),
        ]}),
        strict=False,
    )

    text = render_markdown(render_breakdown(candidate))

    assert "1. Schema (coding)" in text
    assert "2. API key (manual, for a human)" in text
    assert "no separate tickets are created" in text


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


@pytest.mark.asyncio
async def test_approval_posts_one_breakdown_comment_and_no_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure the ticket gets one idempotent comment (FR-006, FR-021)."""
    board = _Board(tmp_path)
    gate = board.approve(_task("t1", "Schema"))
    posted: list[tuple] = []

    async def _record(*args: str) -> None:
        posted.append(args)

    monkeypatch.setattr(bootstrap, "get_gates_service", lambda: board.gates)
    monkeypatch.setattr(
        bootstrap, "get_artifacts_service", lambda: board.artifacts
    )
    monkeypatch.setattr(bootstrap, "_project", _record)

    await bootstrap._project_breakdown("wf-1", gate)

    ((workflow_id, kind, key, payload),) = posted
    text = render_markdown(payload)
    assert (workflow_id, kind) == ("wf-1", "approved_artifact")
    assert key == f"approved_artifact:{gate.id}"
    assert "1. Schema (coding)" in text


def test_no_specialist_can_claim_a_manual_task(tmp_path: Path) -> None:
    """Ensure a manual task is never agent work, even for a role that
    lists the kind (FR-007)."""
    board = _Board(tmp_path)
    board.approve(_task("t1", "Legal sign-off", classification="manual"))
    board.store.set_card_state(board.one("manual_task", "t1").id, "ready")
    anyone = replace(_verifier(), allowed_card_types=("manual_task",))
    claims = ClaimsService(
        store=board.store,
        claims_store=BoardClaimsStore(board_session_factory(tmp_path)),
        roster=SpecialistRoster({"verifier": anyone}),
        max_parallel_read_cards=4, default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )

    with pytest.raises(NoEligibleCardError):
        claims.claim_next_ready_card("wf-1", "verifier")
