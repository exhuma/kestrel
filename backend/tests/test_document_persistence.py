"""Documents at the persistence boundary (feature 046, Principle VI)."""
from __future__ import annotations

from pathlib import Path

from app.documents import (
    EMPTY_DOCUMENT,
    Heading,
    Table,
    Text,
    document,
    paragraph,
)
from app.models_board import WorkCard, Workflow
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactsService
from app.services.board.service import BoardService
from tests.board_test_support import board_session_factory

_BODY = document(
    Heading(2, (Text("Why"),)),
    paragraph(Text("Users need exports.")),
    Table(((Text("Format"),),), (((Text("CSV"),),),)),
)


def _workflow(**overrides: object) -> Workflow:
    fields: dict[str, object] = {
        "id": "wf-1", "source": "github-issue", "task_ref": "o/r#1",
        "repo": "o/r", "base_branch": "main", "source_visibility": "public",
        "title": "Export",
    }
    return Workflow(**{**fields, **overrides})


def test_a_ticket_body_and_prd_are_stored_as_documents(
    tmp_path: Path,
) -> None:
    store = BoardStore(board_session_factory(tmp_path))
    store.create_workflow(_workflow(task_body=_BODY))
    prd = document(paragraph(Text("The plan.")))

    store.record_approved_prd("wf-1", prd)

    workflow = store.get_workflow("wf-1")
    assert workflow.task_body == _BODY
    assert workflow.approved_prd == prd


def test_an_empty_body_and_no_prd_read_back_as_such(tmp_path: Path) -> None:
    store = BoardStore(board_session_factory(tmp_path))
    store.create_workflow(_workflow())

    workflow = store.get_workflow("wf-1")
    assert workflow.task_body == EMPTY_DOCUMENT
    assert workflow.approved_prd is None


def _artifacts(tmp_path: Path) -> ArtifactsService:
    factory = board_session_factory(tmp_path)
    store = BoardStore(factory)
    store.create_workflow(_workflow())
    store.create_card(WorkCard(
        id="card-1", workflow_id="wf-1", kind="understanding", title="t",
        state="done",
    ))
    return ArtifactsService(
        store, BoardArtifactStore(factory), BoardService(store),
    )


def test_a_document_artifact_round_trips(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)

    stored = artifacts.store_document("card-1", "restatement", 1, _BODY)

    assert stored.mime_type == "application/vnd.kestrel.document+json"
    assert artifacts.read_document(stored.id) == _BODY
    assert artifacts.latest_document_for_card("card-1", "restatement") == (
        _BODY
    )


def test_an_unknown_artifact_has_no_document(tmp_path: Path) -> None:
    assert _artifacts(tmp_path).read_document("nope") is None
