"""Tests for T041's wiring: a real workspace provisioned for a
``read_only``/``write`` card's specialist turn (feature 026).

Split out of ``test_board_scheduling.py`` to keep that module under the
repo's 500-line ceiling.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard
from app.services.board.dispatch import DispatchServices, dispatch_ready_work
from app.services.board.specialists import SpecialistRoster
from app.services.board.workspace import WorkspaceService
from tests.test_board_scheduling import (
    _dispatch_services,
    _FakeBackend,
    _specialist,
)
from tests.test_board_workspace import _seed_bare_remote


class _FakeCodeHost:
    """A minimal ``CodeHost`` double over a local bare repo remote."""

    def __init__(self, remote: str) -> None:
        self._remote = remote

    def clone_remote(self, _repo: str) -> str:
        return self._remote

    def git_credential(self) -> tuple[str, str] | None:
        return None


class _FakeTaskSources:
    def __init__(self, code_hosts: dict[str, object]) -> None:
        self.code_hosts = code_hosts


@pytest.mark.asyncio
async def test_write_card_gets_a_real_workspace_and_accept_edits(
    tmp_path: Path,
) -> None:
    bare = _seed_bare_remote(tmp_path)
    roster = SpecialistRoster({"coder": _specialist("coder")})
    services, store = _dispatch_services(tmp_path, roster)
    services = DispatchServices(
        services.claims, services.roster, services.artifacts,
        workspace=WorkspaceService(str(tmp_path / "root")),
        task_sources=_FakeTaskSources(
            {"github-issue": _FakeCodeHost(str(bare))}
        ),
    )
    store.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Implement",
            state="ready",
            eligible_roles=("coder",),
            workspace_permission="write",
        )
    )
    backend = _FakeBackend("<RESULT>implemented</RESULT>")

    await dispatch_ready_work(
        "wf-1", services, lambda _specialist: backend, timeout_seconds=5
    )

    assert store.get_card("card-1").state == "done"
    assert backend.last_request is not None
    assert backend.last_request.permission_mode == "acceptEdits"
    assert backend.last_request.cwd
    assert Path(backend.last_request.cwd, "README.md").exists()


@pytest.mark.asyncio
async def test_write_card_with_no_workspace_configured_stays_claimed(
    tmp_path: Path,
) -> None:
    roster = SpecialistRoster({"coder": _specialist("coder")})
    services, store = _dispatch_services(tmp_path, roster)
    store.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Implement",
            state="ready",
            eligible_roles=("coder",),
            workspace_permission="write",
        )
    )
    backend = _FakeBackend("<RESULT>implemented</RESULT>")

    await dispatch_ready_work(
        "wf-1", services, lambda _specialist: backend, timeout_seconds=5
    )

    assert store.get_card("card-1").state == "claimed"
    assert backend.last_request is None


@pytest.mark.asyncio
async def test_read_only_card_gets_a_workspace_but_stays_in_plan_mode(
    tmp_path: Path,
) -> None:
    bare = _seed_bare_remote(tmp_path)
    roster = SpecialistRoster({"developer": _specialist()})
    services, store = _dispatch_services(tmp_path, roster)
    services = DispatchServices(
        services.claims, services.roster, services.artifacts,
        workspace=WorkspaceService(str(tmp_path / "root")),
        task_sources=_FakeTaskSources(
            {"github-issue": _FakeCodeHost(str(bare))}
        ),
    )
    store.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate",
            state="ready",
            eligible_roles=("developer",),
            workspace_permission="read_only",
        )
    )
    backend = _FakeBackend("<RESULT>found it</RESULT>")

    await dispatch_ready_work(
        "wf-1", services, lambda _specialist: backend, timeout_seconds=5
    )

    assert store.get_card("card-1").state == "done"
    assert backend.last_request.permission_mode == "plan"
    assert Path(backend.last_request.cwd, "README.md").exists()
