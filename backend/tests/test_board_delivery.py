"""Tests for automatic delivery: push + change request on a clean
verification (feature 026, T069).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.document_formats.markdown import render_markdown
from app.models_board import SpecialistDefinition, WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_claims_store import BoardClaimsStore
from app.persistence.board_coordinator_store import BoardCoordinatorStore
from app.persistence.board_projection_store import BoardProjectionStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.claims import ClaimsService
from app.services.board.coordinator import CoordinatorService
from app.services.board.delivery import deliver
from app.services.board.dispatch_ready import (
    DispatchServices,
    dispatch_ready_work,
)
from app.services.board.projections import ProjectionsService
from app.services.board.service import BoardService
from app.services.board.specialists import SpecialistRoster
from app.services.board.workspace import WorkspaceRequest, WorkspaceService
from tests.board_test_support import board_session_factory
from tests.test_board_scheduling import _FakeBackend
from tests.test_board_workspace import _seed_bare_remote

_PR_NUMBER = 7


def _run(*args: str, cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


class _FakeCodeHost:
    def __init__(
        self, remote: str = "", *,
        supports_cr: bool = True, cr_url: str = "https://cr/1",
    ) -> None:
        self._remote = remote
        self._supports_cr = supports_cr
        self._cr_url = cr_url
        self.opened: dict[str, object] | None = None

    def clone_remote(self, _repo: str) -> str:
        return self._remote

    def git_credential(self) -> tuple[str, str] | None:
        return None

    def supports_change_requests(self) -> bool:
        return self._supports_cr

    def file_url(self, repo: str, branch: str, path: str) -> str:
        return f"file://{repo}/{branch}/{path}"

    async def open_change_request(self, repo, **kwargs) -> str:
        self.opened = {"repo": repo, **kwargs}
        return self._cr_url


def _workflow() -> Workflow:
    return Workflow(
        id="wf-1", source="github-issue", task_ref="owner/repo#1",
        repo="owner/repo", base_branch="main", source_visibility="public",
        title="Add a thing",
    )


async def _provisioned_workspace(tmp_path: Path) -> WorkspaceService:
    bare = _seed_bare_remote(tmp_path)
    svc = WorkspaceService(str(tmp_path / "root"))
    dest = await svc.ensure_workspace(
        WorkspaceRequest(str(bare), "owner/repo", "main", "wf-1")
    )
    Path(dest, "notes.txt").write_text("hello\n")
    _run("git", "add", "-A", cwd=Path(dest))
    _run(
        "git", "-c", "commit.gpgsign=false", "commit", "-m", "work",
        cwd=Path(dest),
    )
    return svc


class TestWorkspacePush:
    @pytest.mark.asyncio
    async def test_push_publishes_the_workflow_branch(
        self, tmp_path: Path
    ) -> None:
        svc = await _provisioned_workspace(tmp_path)

        branch = await svc.push("wf-1", None)

        assert branch == "kestrel/board/wf-1"
        mirror = svc.mirror_dir("owner/repo")
        out = _run("git", "-C", mirror, "branch", "-a", cwd=tmp_path)
        assert "kestrel/board/wf-1" in out


class TestWorkspaceTeardown:
    @pytest.mark.asyncio
    async def test_teardown_removes_the_worktree_and_branch(
        self, tmp_path: Path
    ) -> None:
        svc = await _provisioned_workspace(tmp_path)

        await svc.teardown("wf-1", "owner/repo")

        assert not Path(svc.workspace_dir("wf-1"), ".git").exists()
        mirror = svc.mirror_dir("owner/repo")
        out = _run("git", "-C", mirror, "branch", "-a", cwd=tmp_path)
        assert "kestrel/board/wf-1" not in out

    @pytest.mark.asyncio
    async def test_teardown_on_a_never_provisioned_workflow_is_a_no_op(
        self, tmp_path: Path
    ) -> None:
        svc = WorkspaceService(str(tmp_path / "root"))

        await svc.teardown("wf-never", "owner/repo")  # must not raise


class TestDeliver:
    @pytest.mark.asyncio
    async def test_deliver_pushes_and_opens_a_change_request(
        self, tmp_path: Path
    ) -> None:
        svc = await _provisioned_workspace(tmp_path)
        code_host = _FakeCodeHost()

        location = await deliver(_workflow(), code_host, svc)

        assert location == "https://cr/1"
        body = code_host.opened.pop("body")
        assert code_host.opened == {
            "repo": "owner/repo", "head": "kestrel/board/wf-1",
            "base": "main", "title": "Add a thing (owner/repo#1)",
            "draft": True,
        }
        assert render_markdown(body) == (
            "Implements owner/repo#1\n\nOpened by kestrel."
        )

    @pytest.mark.asyncio
    async def test_deliver_reports_a_local_branch_when_unsupported(
        self, tmp_path: Path
    ) -> None:
        svc = await _provisioned_workspace(tmp_path)
        code_host = _FakeCodeHost(supports_cr=False)

        location = await deliver(_workflow(), code_host, svc)

        assert location == "local branch published: kestrel/board/wf-1"
        assert code_host.opened is None

    @pytest.mark.asyncio
    async def test_deliver_updates_rather_than_reopens_an_existing_cr(
        self, tmp_path: Path
    ) -> None:
        """T052: a repair-triggered redelivery must not open a second CR."""
        svc = await _provisioned_workspace(tmp_path)
        code_host = _FakeCodeHost()
        workflow = Workflow(
            id="wf-1", source="github-issue", task_ref="owner/repo#1",
            repo="owner/repo", base_branch="main",
            source_visibility="public", title="Add a thing",
            change_request_number=7,
        )

        location = await deliver(workflow, code_host, svc)

        assert location == "updated existing change request #7"
        assert code_host.opened is None


class _FakeTaskSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def post_comment(self, ref: str, body) -> str:
        self.calls.append((ref, body.plain_text()))
        return "comment-1"


class _FakeTaskSources:
    def __init__(self, code_hosts: dict[str, object], sources: dict) -> None:
        self.code_hosts = code_hosts
        self.sources = sources


def _verifier() -> SpecialistDefinition:
    return SpecialistDefinition(
        id="verifier", label="verifier", purpose="test role",
        allowed_card_types=("verification",), required_abilities=(),
        model_policy="default", workspace_permission="read_only",
        retry_limit=1, prompt="You are the verifier.",
    )


class TestEndToEndDelivery:
    """A clean verification's turn creates and performs delivery through
    the real dispatch_ready_work loop (T069)."""

    @pytest.mark.asyncio
    async def test_a_clean_verification_pushes_and_opens_a_change_request(
        self, tmp_path: Path,
    ) -> None:
        bare = _seed_bare_remote(tmp_path)
        workspace = WorkspaceService(str(tmp_path / "root"))
        dest = await workspace.ensure_workspace(
            WorkspaceRequest(str(bare), "owner/repo", "main", "wf-1")
        )
        Path(dest, "notes.txt").write_text("hello\n")
        _run("git", "add", "-A", cwd=Path(dest))
        _run(
            "git", "-c", "commit.gpgsign=false", "commit", "-m", "work",
            cwd=Path(dest),
        )

        factory = board_session_factory(tmp_path)
        store = BoardStore(factory)
        claims_store = BoardClaimsStore(factory)
        coordinator_store = BoardCoordinatorStore(factory)
        board_service = BoardService(store)
        artifact_store = BoardArtifactStore(factory)
        content_store = BoardArtifactContentStore(tmp_path / "artifacts")
        projections = ProjectionsService(BoardProjectionStore(factory))
        roster = SpecialistRoster({"verifier": _verifier()})
        store.create_workflow(_workflow())
        store.create_card(
            WorkCard(
                id="card-1", workflow_id="wf-1", kind="verification",
                title="Verify", state="ready", eligible_roles=("verifier",),
                workspace_permission="read_only",
            )
        )
        claims = ClaimsService(
            store=store, claims_store=claims_store, roster=roster,
            max_parallel_read_cards=4, default_lease_seconds=60,
            default_workspace_lease_seconds=600,
        )
        artifacts = ArtifactsService(
            store, artifact_store, board_service, content_store
        )
        coordinator = CoordinatorService(
            store, coordinator_store, board_service
        )
        code_host = _FakeCodeHost(
            str(bare), cr_url="https://github.com/owner/repo/pull/7"
        )
        task_source = _FakeTaskSource()
        services = DispatchServices(
            claims, roster, artifacts, workspace=workspace,
            task_sources=_FakeTaskSources(
                {"github-issue": code_host}, {"github-issue": task_source}
            ),
            coordinator=coordinator, projections=projections,
        )
        backend = _FakeBackend("<VERIFIER_FINDINGS>{\"findings\": []}"
                                "</VERIFIER_FINDINGS>")

        await dispatch_ready_work(
            "wf-1", services, lambda _s: backend, timeout_seconds=5
        )

        delivery_cards = [
            c for c in store.list_cards("wf-1") if c.kind == "delivery"
        ]
        assert len(delivery_cards) == 1
        assert delivery_cards[0].state == "done"
        assert code_host.opened["head"] == "kestrel/board/wf-1"
        assert task_source.calls == [(
            "owner/repo#1",
            "Delivered: https://github.com/owner/repo/pull/7",
        )]
        workflow = store.get_workflow("wf-1")
        assert workflow.change_request_number == _PR_NUMBER
        assert workflow.change_request_url == (
            "https://github.com/owner/repo/pull/7"
        )
