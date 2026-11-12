"""The approved PRD goes on the ticket as a file, and a failed upload is
retried as an upload, never as a comment (#64)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.documents import Document
from app.persistence.board_projection_store import BoardProjectionStore
from app.persistence.board_store import BoardStore
from app.services.board.projection_retry import ProjectionRetryService
from app.services.board.projections import ProjectionsService
from app.services.task_sources import TaskSourceRegistry
from tests.announcement_support import announcing
from tests.board_test_support import board_session_factory
from tests.document_helpers import doc
from tests.test_board_decomposition import _WORKFLOW

pytestmark = pytest.mark.integration


@dataclass
class _Source:
    down: bool = False
    files: list[tuple[str, str, str]] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    async def attach_document(self, ref: str, name: str, body: Document) -> str:
        if self.down:
            raise RuntimeError("Jira is down")
        self.files.append((ref, name, body.plain_text()))
        return f"https://jira/{name}"

    async def post_comment(self, _ref: str, body: Document) -> str:
        self.comments.append(body.plain_text())
        return "comment"


def _setup(tmp_path: Path):
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    store.create_workflow(_WORKFLOW)
    projections = ProjectionsService(BoardProjectionStore(factory))
    source = _Source()
    sources = {"github-issue": source}
    retry = ProjectionRetryService(
        projections, store, TaskSourceRegistry(sources, {}),
        interval_seconds=0,
    )
    return announcing(store, projections, sources), retry, source


@pytest.mark.asyncio
async def test_the_prd_is_attached_under_its_name(tmp_path: Path) -> None:
    """Ensure the document becomes a file named by its key."""
    announcements, _retry, source = _setup(tmp_path)

    await announcements.attach(
        "wf-1", "attachment:gate-1:PRD.md", doc("The requirements")
    )

    assert source.files == [("owner/repo#1", "PRD.md", "The requirements")]
    assert source.comments == []


@pytest.mark.asyncio
async def test_a_failed_upload_is_retried_as_an_upload(tmp_path: Path) -> None:
    """Ensure the retry loop uploads the file again, not a comment."""
    announcements, retry, source = _setup(tmp_path)
    source.down = True
    await announcements.attach(
        "wf-1", "attachment:gate-1:PRD-2.md", doc("Revised")
    )
    source.down = False

    assert await retry.poll_once() == 1
    assert source.files == [("owner/repo#1", "PRD-2.md", "Revised")]
    assert source.comments == []
