"""Tests for the change request's body and where delivery records it
(feature 043)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.document_formats.markdown import render_markdown
from app.persistence.board_store import BoardStore
from app.services.board.delivery import deliver
from app.services.board.delivery_body import (
    Screenshots,
    pr_body,
    read_screenshots,
)
from app.services.board.dispatch_delivery import _record_delivery
from app.services.github import GitHubClient, GitHubCodeHost
from app.services.gitlab import GitLabCodeHost
from tests.board_test_support import board_session_factory
from tests.test_board_delivery import (
    _FakeCodeHost,
    _provisioned_workspace,
    _workflow,
)
from tests.test_board_router_views import _client as _router_client

_PR_URL = "https://github.com/owner/repo/pull/7"
_PR_NUMBER = 7


def _url(path: str) -> str:
    return f"https://host/raw/{path}"


def _commit(dest: str, files: dict[str, str | bytes]) -> None:
    for name, content in files.items():
        target = Path(dest, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "shots"],
        cwd=dest, check=True, capture_output=True,
    )



def _md_body(*args) -> str:
    """The body as the code host receives it (Markdown)."""
    return render_markdown(pr_body(*args))

class TestPrBody:
    def test_embeds_each_screenshot_as_an_image(self) -> None:
        shots = Screenshots(images=(
            ".kestrel/screenshots/a-rail.png",
            ".kestrel/screenshots/b-feed.png",
        ))

        body = _md_body("o/r#1", shots, _url)

        assert body == (
            "Implements o/r#1\n\n## Screenshots\n\n"
            "![a-rail](https://host/raw/.kestrel/screenshots/a-rail.png)\n\n"
            "![b-feed](https://host/raw/.kestrel/screenshots/b-feed.png)"
            "\n\nOpened by kestrel."
        )

    def test_states_the_reason_when_there_are_none(self) -> None:
        body = _md_body("o/r#1", Screenshots(note="No browser here."), _url)

        assert "## Screenshots\n\nNo screenshots: No browser here." in body

    def test_has_no_section_without_either(self) -> None:
        body = _md_body("o/r#1", Screenshots(), _url)

        assert body == "Implements o/r#1\n\nOpened by kestrel."


class TestReadScreenshots:
    @pytest.mark.asyncio
    async def test_reads_committed_pngs_and_readme(
        self, tmp_path: Path
    ) -> None:
        svc = await _provisioned_workspace(tmp_path)
        _commit(svc.workspace_dir("wf-1"), {
            ".kestrel/screenshots/rail.png": b"\x89PNG",
            ".kestrel/screenshots/notes.txt": "ignored",
            ".kestrel/screenshots/README.md": "Dialog not reachable.\n",
        })

        shots = await read_screenshots(svc, "wf-1")

        assert shots == Screenshots(
            images=(".kestrel/screenshots/rail.png",),
            note="Dialog not reachable.",
        )

    @pytest.mark.asyncio
    async def test_ignores_uncommitted_files(self, tmp_path: Path) -> None:
        svc = await _provisioned_workspace(tmp_path)
        loose = Path(svc.workspace_dir("wf-1"), ".kestrel/screenshots")
        loose.mkdir(parents=True)
        (loose / "rail.png").write_bytes(b"\x89PNG")

        assert await read_screenshots(svc, "wf-1") == Screenshots()


class TestDeliverBody:
    @pytest.mark.asyncio
    async def test_opens_the_change_request_with_the_screenshots(
        self, tmp_path: Path
    ) -> None:
        svc = await _provisioned_workspace(tmp_path)
        _commit(svc.workspace_dir("wf-1"), {
            ".kestrel/screenshots/rail.png": b"\x89PNG",
        })
        code_host = _FakeCodeHost()

        await deliver(_workflow(), code_host, svc)

        assert render_markdown(code_host.opened["body"]) == (
            "Implements owner/repo#1\n\n## Screenshots\n\n"
            "![rail](file://owner/repo/kestrel/board/wf-1/"
            ".kestrel/screenshots/rail.png)\n\nOpened by kestrel."
        )


class TestFileUrls:
    def test_github_serves_raw_content_from_the_branch(self) -> None:
        client = GitHubClient("https://api.github.com", "tok")
        host = GitHubCodeHost(client, "https://github.com")

        assert host.file_url("o/r", "kestrel/board/wf-1", "a b.png") == (
            "https://github.com/o/r/raw/kestrel/board/wf-1/a%20b.png"
        )

    def test_gitlab_serves_raw_content_from_the_branch(self) -> None:
        host = GitLabCodeHost("https://gitlab.internal", "glpat")

        assert host.file_url("g/svc", "kestrel/board/wf-1", "x.png") == (
            "https://gitlab.internal/g/svc/-/raw/kestrel/board/wf-1/x.png"
        )


class TestRecordDelivery:
    def _services(self, tmp_path: Path) -> tuple[BoardStore, object]:
        store = BoardStore(board_session_factory(tmp_path))
        store.create_workflow(_workflow())
        return store, SimpleNamespace(claims=SimpleNamespace(store=store))

    def test_records_a_fresh_change_requests_url(
        self, tmp_path: Path
    ) -> None:
        store, services = self._services(tmp_path)

        _record_delivery(_workflow(), _PR_URL, services)

        workflow = store.get_workflow("wf-1")
        assert workflow.change_request_number == _PR_NUMBER
        assert workflow.change_request_url == _PR_URL

    def test_an_update_keeps_the_recorded_number_and_url(
        self, tmp_path: Path
    ) -> None:
        store, services = self._services(tmp_path)
        _record_delivery(_workflow(), _PR_URL, services)

        _record_delivery(
            store.get_workflow("wf-1"),
            "updated existing change request #7",
            services,
        )

        workflow = store.get_workflow("wf-1")
        assert workflow.change_request_number == _PR_NUMBER
        assert workflow.change_request_url == _PR_URL

    def test_a_local_branch_records_neither(self, tmp_path: Path) -> None:
        store, services = self._services(tmp_path)

        _record_delivery(
            _workflow(), "local branch published: kestrel/board/wf-1",
            services,
        )

        workflow = store.get_workflow("wf-1")
        assert workflow.change_request_number is None
        assert workflow.change_request_url is None


@pytest.mark.asyncio
async def test_the_snapshot_exposes_the_change_request_url(
    tmp_path: Path,
) -> None:
    """The board snapshot carries the recorded URL (FR-009)."""
    client, store, _claims = _router_client(tmp_path)
    store.record_delivery("wf-1", _PR_NUMBER, _PR_URL)

    async with client as c:
        resp = await c.get("/api/board/workflows/wf-1/board")

    assert resp.json()["change_request_url"] == _PR_URL
