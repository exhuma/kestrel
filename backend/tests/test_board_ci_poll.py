"""Tests for periodic CI-status polling and bounded repair (feature 026,
T052).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.config_models import TaskSourceConfig
from app.models_board import WorkCard, Workflow
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_store import BoardStore
from app.ports import RequiredCiStatus
from app.services.board.ci_poll import CiPollService
from app.services.board.coordinator import CoordinatorService
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_NEW_CR_NUMBER = 99

_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add a thing", change_request_number=42,
)


class _FakeCodeHost:
    def __init__(self, statuses: list[RequiredCiStatus]) -> None:
        self._statuses = statuses
        self.calls: list[tuple[str, int, list[str]]] = []

    async def required_ci_statuses(
        self, repo: str, number: int, names: list[str]
    ) -> list[RequiredCiStatus]:
        self.calls.append((repo, number, names))
        return self._statuses


class _FakeTaskSources:
    def __init__(self, code_hosts: dict[str, object]) -> None:
        self.code_hosts = code_hosts


def _settings(*, max_ci_repair_iterations: int = 2) -> Settings:
    return Settings(
        _env_file=None,
        task_sources=[
            TaskSourceConfig(
                type="github", watched_repos=["owner/repo"],
                required_ci_statuses=["build"],
            )
        ],
        max_ci_repair_iterations=max_ci_repair_iterations,
    )


def _service(
    tmp_path: Path, code_host, *, max_ci_repair_iterations: int = 2
) -> tuple[CiPollService, BoardStore]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    coordinator = CoordinatorService(
        store, BoardCoordinatorStore(factory), board_service
    )
    store.create_workflow(_WORKFLOW)
    service = CiPollService(
        store, coordinator, _FakeTaskSources({"github-issue": code_host}),
        _settings(max_ci_repair_iterations=max_ci_repair_iterations),
    )
    return service, store


class TestBoardStoreCiFields:
    def test_record_delivery_resets_round_and_status(
        self, tmp_path: Path
    ) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        store.create_workflow(_WORKFLOW)
        store.record_ci_status("wf-1", "failed")
        store.record_ci_status("wf-1", "failed")

        store.record_delivery("wf-1", _NEW_CR_NUMBER)

        workflow = store.get_workflow("wf-1")
        assert workflow.change_request_number == _NEW_CR_NUMBER
        assert workflow.ci_repair_round == 0
        assert workflow.ci_status is None

    def test_record_ci_status_increments_round_only_on_failure(
        self, tmp_path: Path
    ) -> None:
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        store.create_workflow(_WORKFLOW)

        store.record_ci_status("wf-1", "pending")
        assert store.get_workflow("wf-1").ci_repair_round == 0

        round_after = store.record_ci_status("wf-1", "failed")
        assert round_after == 1
        assert store.get_workflow("wf-1").ci_status == "failed"


class TestEligibility:
    @pytest.mark.asyncio
    async def test_a_workflow_with_no_change_request_is_not_polled(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost([RequiredCiStatus("build", "passed")])
        service, store = _service(tmp_path, code_host)
        store.record_delivery("wf-1", None)

        await service.poll_once()

        assert code_host.calls == []

    @pytest.mark.asyncio
    async def test_a_source_with_no_required_checks_is_not_polled(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost([RequiredCiStatus("build", "passed")])
        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        board_service = BoardService(store)
        coordinator = CoordinatorService(
            store, BoardCoordinatorStore(factory), board_service
        )
        store.create_workflow(_WORKFLOW)
        settings = Settings(_env_file=None)  # no task_sources configured
        service = CiPollService(
            store, coordinator, _FakeTaskSources({"github-issue": code_host}),
            settings,
        )

        await service.poll_once()

        assert code_host.calls == []

    @pytest.mark.asyncio
    async def test_a_passed_workflow_is_never_polled_again(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost([RequiredCiStatus("build", "passed")])
        service, _store = _service(tmp_path, code_host)

        await service.poll_once()
        await service.poll_once()

        assert len(code_host.calls) == 1


class TestPolling:
    @pytest.mark.asyncio
    async def test_pending_records_pending_and_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost([RequiredCiStatus("build", "pending")])
        service, store = _service(tmp_path, code_host)

        await service.poll_once()

        assert store.get_workflow("wf-1").ci_status == "pending"
        assert store.list_cards("wf-1") == []

    @pytest.mark.asyncio
    async def test_passed_records_passed_and_creates_nothing(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost([RequiredCiStatus("build", "passed")])
        service, store = _service(tmp_path, code_host)

        await service.poll_once()

        assert store.get_workflow("wf-1").ci_status == "passed"
        assert store.list_cards("wf-1") == []

    @pytest.mark.asyncio
    async def test_a_failure_within_budget_creates_a_repair_card(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost(
            [RequiredCiStatus("build", "failed", "lint error")]
        )
        service, store = _service(tmp_path, code_host)

        await service.poll_once()

        workflow = store.get_workflow("wf-1")
        assert workflow.ci_status == "failed"
        assert workflow.ci_repair_round == 1
        cards = store.list_cards("wf-1")
        assert len(cards) == 1
        assert cards[0].kind == "implementation"
        assert cards[0].eligible_roles == ("coder",)
        assert "lint error" in cards[0].title

    @pytest.mark.asyncio
    async def test_a_failure_past_budget_escalates_instead(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost(
            [RequiredCiStatus("build", "failed", "still red")]
        )
        service, store = _service(
            tmp_path, code_host, max_ci_repair_iterations=0
        )

        await service.poll_once()

        cards = store.list_cards("wf-1")
        assert len(cards) == 1
        assert cards[0].kind == "coordinator_review"
        assert "budget exhausted" in cards[0].title

    @pytest.mark.asyncio
    async def test_escalation_stops_further_polling(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost(
            [RequiredCiStatus("build", "failed", "still red")]
        )
        service, _store = _service(
            tmp_path, code_host, max_ci_repair_iterations=0
        )

        await service.poll_once()
        await service.poll_once()

        assert len(code_host.calls) == 1

    @pytest.mark.asyncio
    async def test_a_provider_error_does_not_crash_the_sweep(
        self, tmp_path: Path
    ) -> None:
        class _RaisingCodeHost:
            async def required_ci_statuses(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        service, store = _service(tmp_path, _RaisingCodeHost())

        await service.poll_once()  # must not raise

        assert store.get_workflow("wf-1").ci_status is None


class TestUnrelatedCardsIgnored:
    """A card that happens to exist must never confuse eligibility."""

    @pytest.mark.asyncio
    async def test_an_existing_unrelated_card_does_not_block_polling(
        self, tmp_path: Path
    ) -> None:
        code_host = _FakeCodeHost([RequiredCiStatus("build", "passed")])
        service, store = _service(tmp_path, code_host)
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="analysis",
                title="Unrelated", state="done",
            )
        )

        await service.poll_once()

        assert store.get_workflow("wf-1").ci_status == "passed"
