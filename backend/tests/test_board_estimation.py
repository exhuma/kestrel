"""Tests for estimation routing into CAB-2 (feature 030, US3/US1)."""
import json
from pathlib import Path

import pytest

from app.models_board import SpecialistDefinition, WorkCard
from app.persistence.board_claims_store import BoardClaimsStore
from app.services.board.claims import ClaimsService
from app.services.board.decomposition import (
    RoutingServices,
    route_decomposition_result,
)
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.estimation import (
    PROPOSAL_LOGICAL_NAME,
    SUMMARY_LOGICAL_NAME,
    estimation_context,
    route_estimation_result,
)
from app.services.board.exec_summary import HEADER
from app.services.board.specialists import SpecialistRoster
from app.services.board.workspace import WorkspaceService
from tests.board_test_support import board_session_factory
from tests.test_board_decomposition import _setup
from tests.test_board_dispatch_workspace import (
    _FakeCodeHost,
    _FakeTaskSources,
)
from tests.test_board_scheduling import _FakeBackend
from tests.test_board_workspace import _seed_bare_remote

_PM_OUTPUT = (
    "<DECOMPOSITION>"
    + json.dumps(
        {
            "summary": "Add an audit table, then get legal sign-off.",
            "tasks": [
                {"title": "Audit table", "body": "b1",
                 "classification": "coding"},
                {"title": "Legal sign-off", "body": "b2",
                 "classification": "manual"},
            ],
        }
    )
    + "</DECOMPOSITION>"
)

_CODING = {
    "task_node_id": "t1", "size": "M", "confidence": "low",
    "man_hours": 6, "agent_tokens": 400000, "review_hours": 1.5,
    "risks": ["schema migration"], "rationale": "one table",
}
_MANUAL = {
    "task_node_id": "t2", "size": "S", "confidence": "high",
    "man_hours": 2, "agent_tokens": 0, "review_hours": 0,
    "risks": [], "rationale": "one email",
}


def _estimates(*entries: dict) -> str:
    return (
        "<ESTIMATES>" + json.dumps({"estimates": list(entries)})
        + "</ESTIMATES>"
    )


def _estimation_setup(
    tmp_path: Path,
) -> tuple[RoutingServices, WorkCard]:
    """Route a valid pm proposal; return the estimation card it made."""
    store, coordinator, gates, artifacts, card, _ = _setup(tmp_path)
    services = RoutingServices(store, coordinator, gates, artifacts)
    route_decomposition_result(_PM_OUTPUT, card, services)
    estimation = next(
        c for c in store.list_cards("wf-1") if c.kind == "estimation"
    )
    return services, estimation


def _new_kinds(services: RoutingServices) -> list[str]:
    return [
        c.kind for c in services.store.list_cards("wf-1")
        if c.kind not in {"decomposition", "estimation"}
    ]


def _gate(services: RoutingServices) -> WorkCard:
    return next(
        c for c in services.store.list_cards("wf-1")
        if c.kind == "decomposition_gate"
    )


class TestContext:
    def test_the_estimator_sees_the_normalized_candidate(
        self, tmp_path: Path
    ) -> None:
        services, estimation = _estimation_setup(tmp_path)

        context = estimation_context(estimation, services)

        assert '"task_node_id": "t1"' in context
        assert '"classification": "manual"' in context

    def test_a_card_without_a_candidate_gets_no_context(
        self, tmp_path: Path
    ) -> None:
        services, estimation = _estimation_setup(tmp_path)
        orphan = WorkCard(
            id="card-x", workflow_id="wf-1", kind="estimation",
            title="x", state="ready",
        )
        services.store.create_card(orphan)
        assert estimation_context(orphan, services) == ""
        assert estimation_context(estimation, services) != ""


class TestValidEstimates:
    def test_valid_estimates_open_exactly_one_cab2_gate(
        self, tmp_path: Path
    ) -> None:
        services, estimation = _estimation_setup(tmp_path)

        route_estimation_result(
            _estimates(_CODING, _MANUAL), estimation, services
        )

        assert _new_kinds(services) == ["decomposition_gate"]
        gate = _gate(services)
        assert gate.state == "awaiting_human"
        assert gate.title == "Approve decomposition (1 coding, 1 manual)"

    def test_the_gate_targets_the_structured_proposal(
        self, tmp_path: Path
    ) -> None:
        """Ensure estimates stay machine-readable (FR-016)."""
        services, estimation = _estimation_setup(tmp_path)
        route_estimation_result(
            _estimates(_CODING, _MANUAL), estimation, services
        )

        record = services.gates.get_gate(_gate(services).id)
        proposal = json.loads(
            services.artifacts.read_content(record.target_artifact_id)
        )
        assert proposal["tasks"][0]["estimate"]["agent_tokens"] == (
            _CODING["agent_tokens"]
        )
        assert proposal["tasks"][1]["classification"] == "manual"
        assert services.artifacts.producer_card_id(
            record.target_artifact_id
        ) == estimation.id
        assert services.artifacts.latest_content_for_card(
            estimation.id, PROPOSAL_LOGICAL_NAME
        ) is not None

    def test_the_executive_summary_is_the_gates_own_artifact(
        self, tmp_path: Path
    ) -> None:
        services, estimation = _estimation_setup(tmp_path)
        route_estimation_result(
            _estimates(_CODING, _MANUAL), estimation, services
        )

        summary = services.artifacts.latest_content_for_card(
            _gate(services).id, SUMMARY_LOGICAL_NAME
        )
        assert summary is not None
        assert HEADER in summary
        assert "Add an audit table" in summary
        assert "- **Human effort**: 8.0 man-hours" in summary


class TestInvalidEstimates:
    @pytest.mark.parametrize(
        "text",
        [
            "no block",
            "<ESTIMATES>{not json</ESTIMATES>",
            _estimates(_CODING),
            _estimates(_CODING, _MANUAL, {**_MANUAL, "task_node_id": "t9"}),
            _estimates(_CODING, _CODING, _MANUAL),
            _estimates(_CODING, {**_MANUAL, "agent_tokens": 5}),
            _estimates(_CODING, {**_MANUAL, "review_hours": 1}),
            _estimates({**_CODING, "review_hours": 0}, _MANUAL),
            _estimates({**_CODING, "agent_tokens": 0}, _MANUAL),
            _estimates(_CODING, {**_MANUAL, "man_hours": 0}),
            _estimates(_CODING, {**_MANUAL, "size": "huge"}),
        ],
        ids=[
            "no-block", "bad-json", "missing-task", "unknown-task",
            "duplicate-task", "manual-with-tokens", "manual-with-review",
            "coding-without-review", "coding-without-tokens",
            "zero-man-hours", "bad-size",
        ],
    )
    def test_an_invalid_estimate_escalates_and_opens_no_gate(
        self, tmp_path: Path, text: str
    ) -> None:
        services, estimation = _estimation_setup(tmp_path)

        route_estimation_result(text, estimation, services)

        assert _new_kinds(services) == ["coordinator_review"]

    def test_no_second_gate_while_one_is_awaiting(
        self, tmp_path: Path
    ) -> None:
        """Ensure one decomposition never yields two CAB-2 gates."""
        services, estimation = _estimation_setup(tmp_path)
        text = _estimates(_CODING, _MANUAL)
        route_estimation_result(text, estimation, services)

        retried = WorkCard(
            id=estimation.id, workflow_id="wf-1", kind="estimation",
            title=estimation.title, state="done", attempt_count=2,
        )
        route_estimation_result(text, retried, services)

        assert sorted(_new_kinds(services)) == [
            "coordinator_review", "decomposition_gate",
        ]


def _role(role_id: str, kinds: tuple[str, ...]) -> SpecialistDefinition:
    return SpecialistDefinition(
        id=role_id, label=role_id, purpose="test role",
        allowed_card_types=kinds, required_abilities=(),
        model_policy="default", workspace_permission="read_only",
        retry_limit=1, prompt=f"You are the {role_id}.",
    )


class TestEndToEnd:
    """pm turn → estimation card → developer turn → CAB-2, through the
    real dispatch loop."""

    @pytest.mark.asyncio
    async def test_decomposition_then_estimation_opens_cab2(
        self, tmp_path: Path
    ) -> None:
        bare = _seed_bare_remote(tmp_path)
        store, coordinator, gates, artifacts, _card, _ = _setup(tmp_path)
        store.create_card(
            WorkCard(
                id="card-pm", workflow_id="wf-1", kind="decomposition",
                title="Decompose", state="ready", eligible_roles=("pm",),
            )
        )
        roster = SpecialistRoster(
            {
                "pm": _role("pm", ("decomposition",)),
                "developer": _role("developer", ("estimation",)),
            }
        )
        claims = ClaimsService(
            store=store, claims_store=BoardClaimsStore(
                board_session_factory(tmp_path)
            ),
            roster=roster, max_parallel_read_cards=4,
            default_lease_seconds=60, default_workspace_lease_seconds=600,
        )
        services = DispatchServices(
            claims, roster, artifacts, coordinator=coordinator, gates=gates,
            workspace=WorkspaceService(str(tmp_path / "root")),
            task_sources=_FakeTaskSources(
                {"github-issue": _FakeCodeHost(str(bare))}
            ),
        )
        backends = {
            "pm": _FakeBackend(_PM_OUTPUT),
            "developer": _FakeBackend(_estimates(_CODING, _MANUAL)),
        }

        for _ in range(2):
            await dispatch_ready_work(
                "wf-1", services, lambda s: backends[s.id],
                timeout_seconds=5,
            )

        developer_prompt = backends["developer"].last_request.prompt
        assert '"task_node_id": "t2"' in developer_prompt
        gate = next(
            c for c in store.list_cards("wf-1")
            if c.kind == "decomposition_gate"
        )
        assert gate.title == "Approve decomposition (1 coding, 1 manual)"
