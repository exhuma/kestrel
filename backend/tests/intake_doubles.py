"""Shared in-memory doubles for ingestion tests (feature 032).

``IngestionService`` creates the request first, screens it in place, and
then passes or quarantines it through ``BoardService``'s screening
lifecycle. These doubles record each step, so an ingestion test can
assert what happened without a database. The real lifecycle is covered
by ``test_board_intake_screening.py``.
"""
from __future__ import annotations

from dataclasses import replace

from app.models_board import WorkCard, Workflow
from app.models_board_records import AcceptedTaskIntake, IntakeOutcome
from app.persistence.board_store import WorkflowAlreadyExistsError
from app.services.board.intake import screening_card
from app.services.board.quarantine import ExistingWorkflowIntake
from app.services.ingestion import BoardIntake


class FakeIntakeQuarantine:
    """Releases (or quarantines) every intake, recording each."""

    def __init__(self, *, released: bool = True) -> None:
        self.released = released
        self.calls: list[ExistingWorkflowIntake] = []

    async def intake_for_existing_workflow(
        self, intake: ExistingWorkflowIntake
    ) -> IntakeOutcome:
        self.calls.append(intake)
        workflow_id = intake.workflow.id if intake.workflow else None
        if self.released:
            return IntakeOutcome(released=True, safe_content=intake.content)
        return IntakeOutcome(
            released=False, security_review_id="review-1",
            workflow_id=workflow_id, card_id="card-review",
        )


class FakeIntakeBoard:
    """Records the screening lifecycle of every request it opens."""

    def __init__(
        self, *, raise_duplicate: bool = False, fail: bool = False
    ) -> None:
        self.calls: list[AcceptedTaskIntake] = []
        self.workflows: list[Workflow] = []
        self.cards: dict[str, list[WorkCard]] = {}
        self.passed: list[tuple[str, str, str]] = []
        self.settled: list[tuple[str, str]] = []
        self.announced: list[str] = []
        self._raise_duplicate = raise_duplicate
        self._fail = fail

    def list_workflows(self) -> list[Workflow]:
        return self.workflows

    def get_workflow(self, workflow_id: str) -> Workflow | None:
        return next((w for w in self.workflows if w.id == workflow_id), None)

    def list_cards(self, workflow_id: str) -> list[WorkCard]:
        return self.cards.get(workflow_id, [])

    def open_screening(
        self, intake: AcceptedTaskIntake
    ) -> tuple[Workflow, WorkCard]:
        if self._fail:
            raise RuntimeError("create failed")
        if self._raise_duplicate:
            raise WorkflowAlreadyExistsError(
                f"{intake.source}:{intake.task_ref}"
            )
        self.calls.append(intake)
        workflow = Workflow(
            id=f"wf-{len(self.workflows)}", source=intake.source,
            task_ref=intake.task_ref, repo=intake.repo,
            base_branch=intake.base_branch,
            source_visibility=intake.source_visibility, title=intake.title,
        )
        card = screening_card(workflow.id)
        self.workflows.append(workflow)
        self.cards[workflow.id] = [card]
        self.announced.append(workflow.id)
        return workflow, card

    def pass_screening(
        self, workflow_id: str, *, title: str, body: str,
        card_id: str | None,
    ) -> None:
        self.passed.append((workflow_id, title, body))
        if card_id is not None:
            self._set(workflow_id, card_id, "done")

    def settle_screening(
        self, card_id: str, state: str, *, event_type: str, wake: bool
    ) -> None:
        del event_type, wake
        self.settled.append((card_id, state))
        for workflow_id, cards in self.cards.items():
            if any(c.id == card_id for c in cards):
                self._set(workflow_id, card_id, state)

    def announce(self, workflow_id: str) -> None:
        self.announced.append(workflow_id)

    def _set(self, workflow_id: str, card_id: str, state: str) -> None:
        self.cards[workflow_id] = [
            replace(c, state=state) if c.id == card_id else c
            for c in self.cards[workflow_id]
        ]


def fake_board_intake(
    *, released: bool = True, board: FakeIntakeBoard | None = None
) -> BoardIntake:
    """A ``BoardIntake`` over the doubles above."""
    return BoardIntake(
        FakeIntakeQuarantine(released=released), board or FakeIntakeBoard()
    )
