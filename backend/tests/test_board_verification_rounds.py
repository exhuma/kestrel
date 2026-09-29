"""Tests for verification rounds on approved CAB-2 tasks (feature 031,
research R6)."""
from __future__ import annotations

from pathlib import Path

from app.models_board import WorkCard
from app.persistence.board_store import BoardStore
from app.services.board.coordinator import CoordinatorService
from app.services.board.verification import route_verifier_result
from app.services.board.verification_rounds import RoundContext
from tests.test_board_decomposition import _setup

_CAP = 2


def _findings(*categories: str) -> str:
    entries = ",".join(
        f'{{"category": "{c}", "summary": "issue {i}"}}'
        for i, c in enumerate(categories)
    )
    return f'<VERIFIER_FINDINGS>{{"findings": [{entries}]}}</VERIFIER_FINDINGS>'


class _Task:
    """One approved task, implemented, with its round-1 verification."""

    def __init__(self, tmp_path: Path) -> None:
        store, coordinator, _gates, _artifacts, _card, _ = _setup(tmp_path)
        self.store: BoardStore = store
        self.coordinator: CoordinatorService = coordinator
        self.store.create_card(
            WorkCard(
                id="impl", workflow_id="wf-1", kind="implementation",
                title="Schema", state="done", task_node_id="t1",
            )
        )
        self.verification = self.add_verification("ver-1")

    def add_verification(self, card_id: str) -> WorkCard:
        card = WorkCard(
            id=card_id, workflow_id="wf-1", kind="verification",
            title="Verify: Schema", state="done", attempt_count=1,
            task_node_id="t1",
        )
        self.store.create_card(card)
        return card

    def route(self, text: str, card: WorkCard | None = None) -> None:
        route_verifier_result(
            text, card or self.verification, self.coordinator,
            RoundContext(self.store.list_cards, _CAP),
        )

    def new_cards(self) -> list[WorkCard]:
        return [
            c for c in self.store.list_cards("wf-1")
            if c.id not in {"impl", "ver-1", "ver-2", "card-1"}
        ]

    def depends_on(self, card: WorkCard) -> set[str]:
        return {
            r.depends_on_card_id for r in self.store.list_relations("wf-1")
            if r.card_id == card.id
        }


def test_a_clean_result_creates_nothing(tmp_path: Path) -> None:
    task = _Task(tmp_path)

    task.route(_findings())

    assert task.new_cards() == []


def test_a_fix_is_verified_again_within_the_cap(tmp_path: Path) -> None:
    """Ensure remediation and its re-verification stay on the task."""
    task = _Task(tmp_path)

    task.route(_findings("nonconformance", "verification_gap"))

    fixes = [c for c in task.new_cards() if c.kind == "implementation"]
    (again,) = [c for c in task.new_cards() if c.kind == "verification"]
    assert {c.task_node_id for c in task.new_cards()} == {"t1"}
    assert again.title == "Verify: Schema"
    assert again.state == "waiting_dependency"
    assert again.eligible_roles == ("verifier",)
    assert task.depends_on(again) == {c.id for c in fixes}


def test_the_cap_escalates_instead_of_fixing_again(tmp_path: Path) -> None:
    """Ensure a task that keeps failing stops and asks for review."""
    task = _Task(tmp_path)
    second = task.add_verification("ver-2")

    task.route(_findings("nonconformance"), second)

    (review,) = task.new_cards()
    assert review.kind == "coordinator_review"
    assert review.title == "Verification cap reached: Schema"
    assert review.task_node_id == "t1"


def test_escalations_are_tied_to_the_task(tmp_path: Path) -> None:
    task = _Task(tmp_path)

    task.route(_findings("ambiguity"))

    (review,) = task.new_cards()
    assert (review.kind, review.task_node_id) == ("coordinator_review", "t1")


def test_an_untagged_verification_is_routed_as_before(
    tmp_path: Path,
) -> None:
    """Ensure coordinator-created work keeps the pre-031 behaviour."""
    task = _Task(tmp_path)
    plain = WorkCard(
        id="ver-plain", workflow_id="wf-1", kind="verification",
        title="Check", state="done", attempt_count=1,
    )
    task.store.create_card(plain)

    task.route(_findings("nonconformance"), plain)

    (fix,) = [c for c in task.new_cards() if c.id != "ver-plain"]
    assert (fix.kind, fix.task_node_id) == ("implementation", None)
