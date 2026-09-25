"""Tests for the dev-only workflow reset helpers (feature 026, T069).

Temporary, per the module's own docstring — these tests exist only to
keep the helper correct while it's still in the codebase, not to give it
production-grade coverage.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.models_board import CardState, ClaimRequest, WorkCard, Workflow
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_store import BoardStore
from app.services.board.claims import ClaimsService
from app.services.board.dev_reset import (
    DevActionNotAllowedError,
    cleanup_workflow,
    rerun_workflow,
)
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.board.workspace import WorkspaceRequest, WorkspaceService
from tests.board_test_support import board_session_factory
from tests.test_board_workspace import _seed_bare_remote

_PRIVATE_WORKFLOW = Workflow(
    id="wf-1", source="local", task_ref="local/task-1", repo="owner/repo",
    base_branch="main", source_visibility="private", title="Try a thing",
)
_PUBLIC_WORKFLOW = Workflow(
    id="wf-1", source="github-issue", task_ref="owner/repo#1",
    repo="owner/repo", base_branch="main", source_visibility="public",
    title="Add a thing",
)


def _run(*args: str, cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _services(
    tmp_path: Path, workflow: Workflow
) -> tuple[BoardStore, BoardService, ClaimsService, WorkspaceService]:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    board_service = BoardService(store)
    claims_store = BoardClaimsStore(factory)
    claims = ClaimsService(
        store=store, claims_store=claims_store, roster=SpecialistRoster({}),
        max_parallel_read_cards=4, default_lease_seconds=60,
        default_workspace_lease_seconds=600,
    )
    workspace = WorkspaceService(str(tmp_path / "root"))
    store.create_workflow(workflow)
    return store, board_service, claims, workspace


class TestCleanupWorkflow:
    @pytest.mark.asyncio
    async def test_rejects_a_public_workflow(self, tmp_path: Path) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PUBLIC_WORKFLOW
        )

        with pytest.raises(DevActionNotAllowedError):
            await cleanup_workflow(
                "wf-1", store=store, board_service=board_service,
                claims=claims, workspace=workspace,
            )

    @pytest.mark.asyncio
    async def test_rejects_an_unknown_workflow(self, tmp_path: Path) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PRIVATE_WORKFLOW
        )

        with pytest.raises(DevActionNotAllowedError):
            await cleanup_workflow(
                "wf-missing", store=store, board_service=board_service,
                claims=claims, workspace=workspace,
            )

    @pytest.mark.asyncio
    async def test_cancels_open_cards_but_not_terminal_ones(
        self, tmp_path: Path
    ) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PRIVATE_WORKFLOW
        )
        store.create_card(
            WorkCard(
                id="card-ready", workflow_id="wf-1", kind="analysis",
                title="Ready", state="ready",
            )
        )
        store.create_card(
            WorkCard(
                id="card-done", workflow_id="wf-1", kind="analysis",
                title="Done", state="done",
            )
        )

        await cleanup_workflow(
            "wf-1", store=store, board_service=board_service,
            claims=claims, workspace=workspace,
        )

        assert store.get_card("card-ready").state == "cancelled"
        assert store.get_card("card-done").state == "done"

    @pytest.mark.asyncio
    async def test_releases_an_active_claim(self, tmp_path: Path) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PRIVATE_WORKFLOW
        )
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="analysis",
                title="Claimed", state="claimed",
            )
        )
        claims.claims_store.claim_card(
            ClaimRequest("card-1", "developer", 600)
        )

        await cleanup_workflow(
            "wf-1", store=store, board_service=board_service,
            claims=claims, workspace=workspace,
        )

        assert claims.claims_store.get_active_lease("card-1") is None
        assert store.get_card("card-1").state == "cancelled"

    @pytest.mark.asyncio
    async def test_tears_down_a_provisioned_workspace(
        self, tmp_path: Path
    ) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PRIVATE_WORKFLOW
        )
        bare = _seed_bare_remote(tmp_path)
        await workspace.ensure_workspace(
            WorkspaceRequest(str(bare), "owner/repo", "main", "wf-1")
        )

        await cleanup_workflow(
            "wf-1", store=store, board_service=board_service,
            claims=claims, workspace=workspace,
        )

        assert not Path(workspace.workspace_dir("wf-1"), ".git").exists()


class TestRerunWorkflow:
    @pytest.mark.asyncio
    async def test_reopens_the_same_workflow_at_understanding_gate(
        self, tmp_path: Path
    ) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PRIVATE_WORKFLOW
        )
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="implementation",
                title="Old work", state="ready",
            )
        )

        await rerun_workflow(
            "wf-1", store=store, board_service=board_service,
            claims=claims, workspace=workspace,
        )

        assert store.get_card("card-1").state == "cancelled"
        cards = store.list_cards("wf-1")
        gates = [c for c in cards if c.kind == "understanding_gate"]
        assert len(gates) == 1
        assert gates[0].state == CardState.AWAITING_HUMAN.value
        assert store.get_workflow("wf-1").id == "wf-1"

    @pytest.mark.asyncio
    async def test_rejects_a_public_workflow(self, tmp_path: Path) -> None:
        store, board_service, claims, workspace = _services(
            tmp_path, _PUBLIC_WORKFLOW
        )

        with pytest.raises(DevActionNotAllowedError):
            await rerun_workflow(
                "wf-1", store=store, board_service=board_service,
                claims=claims, workspace=workspace,
            )
