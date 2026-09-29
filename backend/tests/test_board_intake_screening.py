"""Screening a picked-up request in place, against the real board and
quarantine (feature 032, #68)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.backends.base import TurnRequest, TurnResult
from app.config import Settings
from app.config_models import TaskSourceConfig
from app.persistence.board_quarantine_store import BoardQuarantineStore
from app.persistence.board_store import BoardStore
from app.persistence.dismissal_store import DismissalStore
from app.ports import Task
from app.services.board.quarantine import QuarantineService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.ingestion import BoardIntake, IngestionService
from tests.board_test_support import board_session_factory
from tests.test_board_quarantine import _FakeBackendPolicy, _input_security

_SAFE = (
    '<CLASSIFICATION>{"safe": true, "category": "benign", "reason": "ok"}'
    "</CLASSIFICATION>"
)
_SUSPECT = (
    '<CLASSIFICATION>{"safe": false, "category": "prompt_injection", '
    '"reason": "asks to ignore instructions"}</CLASSIFICATION>'
)


class _Classifier:
    """Answers the classification, first checking what the board shows
    while it is still being screened."""

    def __init__(self, verdict: str, rig: _Rig) -> None:
        self.verdict = verdict
        self._rig = rig
        self.seen_during_screening: list[tuple[str, str, str]] = []

    async def run_turn(self, _req: TurnRequest) -> TurnResult:
        for workflow in self._rig.store.list_workflows():
            for card in self._rig.store.list_cards(workflow.id):
                self.seen_during_screening.append(
                    (workflow.title, card.title, card.state)
                )
        return TurnResult(session_id="s", final_text=self.verdict)


class _Source:
    async def get_task(self, ref: str) -> Task:
        return Task(ref=ref, title="Add CSV export", body="Please add it.")

    def visibility(self) -> str:
        return "public"


class _Sources:
    sources = {"github-issue": _Source()}
    code_hosts: dict[str, object] = {}


class _Rig:
    def __init__(self, tmp_path: Path, verdict: str) -> None:
        factory = board_session_factory(tmp_path)
        self.store = BoardStore(factory)
        self.wakes: list[str] = []
        board = BoardService(self.store, on_mutation=self.wakes.append)
        self.classifier = _Classifier(verdict, self)
        self.quarantine = QuarantineService(
            BoardQuarantineStore(factory),
            SpecialistRoster({"input-security": _input_security()}),
            _FakeBackendPolicy(self.classifier),
            max_bytes=65536, classify_timeout_seconds=5,
        )
        self.ingestion = IngestionService(
            Settings(task_sources=[
                TaskSourceConfig(type="github", watched_repos=["o/r"])
            ]),
            _Sources(), DismissalStore(factory),
            BoardIntake(self.quarantine, board),
        )

    async def pick_up(self) -> str:
        workflow_id = await self.ingestion.maybe_start_run(
            source="github-issue", task_ref="o/r#1", code_repo="o/r"
        )
        assert workflow_id is not None
        return workflow_id

    def kinds(self, workflow_id: str) -> list[tuple[str, str]]:
        return [
            (c.kind, c.state) for c in self.store.list_cards(workflow_id)
        ]


@pytest.mark.asyncio
async def test_the_request_is_on_the_board_while_it_is_screened(
    tmp_path: Path,
) -> None:
    """Ensure a slow classification is visible, and shows no content
    (FR-001/FR-002)."""
    rig = _Rig(tmp_path, _SAFE)

    await rig.pick_up()

    assert rig.classifier.seen_during_screening == [
        ("o/r#1", "Screening input", "claimed")
    ]


@pytest.mark.asyncio
async def test_passing_screening_starts_understanding(tmp_path: Path) -> None:
    """Ensure the request gets its content and pm's restatement card,
    and the coordinator wakes only once screening has passed (FR-003)."""
    rig = _Rig(tmp_path, _SAFE)

    workflow_id = await rig.pick_up()

    workflow = rig.store.get_workflow(workflow_id)
    assert (workflow.title, workflow.task_body) == (
        "Add CSV export", "Please add it."
    )
    assert rig.kinds(workflow_id) == [
        ("security_review", "done"), ("understanding", "ready"),
    ]
    assert rig.wakes == [workflow_id]


@pytest.mark.asyncio
async def test_a_suspect_ticket_is_quarantined_on_the_same_request(
    tmp_path: Path,
) -> None:
    """Ensure one request per ticket, quarantined in place, with no
    content and no coordinator wake (FR-004, SC-002)."""
    rig = _Rig(tmp_path, _SUSPECT)

    workflow_id = await rig.pick_up()

    assert [w.id for w in rig.store.list_workflows()] == [workflow_id]
    assert rig.kinds(workflow_id) == [
        ("security_review", "cancelled"), ("security_review", "quarantined"),
    ]
    assert rig.store.get_workflow(workflow_id).task_body == ""
    assert rig.wakes == []


@pytest.mark.asyncio
async def test_releasing_the_quarantine_continues_the_request(
    tmp_path: Path,
) -> None:
    """Ensure a release picks the request up where it stopped (FR-005)."""
    rig = _Rig(tmp_path, _SUSPECT)
    workflow_id = await rig.pick_up()
    (review_card,) = [
        c for c in rig.store.list_cards(workflow_id)
        if c.state == "quarantined"
    ]
    review = rig.quarantine.review_for_card(review_card.id)

    rig.quarantine.release(review.id)
    await rig.ingestion.continue_intake(workflow_id)

    assert ("understanding", "ready") in rig.kinds(workflow_id)
    assert rig.store.get_workflow(workflow_id).task_body == "Please add it."


@pytest.mark.asyncio
async def test_a_second_poll_starts_nothing_new(tmp_path: Path) -> None:
    rig = _Rig(tmp_path, _SAFE)
    workflow_id = await rig.pick_up()

    again = await rig.ingestion.maybe_start_run(
        source="github-issue", task_ref="o/r#1", code_repo="o/r"
    )

    assert again is None
    assert [w.id for w in rig.store.list_workflows()] == [workflow_id]
