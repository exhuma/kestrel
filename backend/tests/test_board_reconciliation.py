"""Card-result acceptance, dependency cascade, and reconciliation-card
creation tests for ``ArtifactsService`` (feature 026, T030).

Distinct from ``test_board_coordinator.py``'s reconciliation-card tests:
those cover a coordinator-*decided* reconciliation action; this file
covers automatic reconciliation-card creation driven by two specialists'
outputs actually conflicting (FR-026), plus the dependency-ready cascade
that follows an accepted result.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models_board import CardRelation, HandoffArtifact, WorkCard, Workflow
from app.persistence.board_artifact_content_store import (
    BoardArtifactContentStore,
)
from app.persistence.board_artifact_store import BoardArtifactStore
from app.persistence.board_store import BoardStore
from app.services.board.artifacts import ArtifactDraft, ArtifactsService
from app.services.board.service import BoardService

_WORKFLOW = Workflow(
    id="wf-1",
    source="github-issue",
    task_ref="owner/repo#1",
    repo="owner/repo",
    base_branch="main",
    source_visibility="public",
    title="Add a thing",
)

_Stores = tuple[ArtifactsService, BoardStore, BoardArtifactStore]


def _factory(tmp_path: Path) -> sessionmaker:
    database = tmp_path / "board.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    return sessionmaker(bind=sa.create_engine(f"sqlite:///{database}"))


def _service(tmp_path: Path) -> _Stores:
    factory = _factory(tmp_path)
    store = BoardStore(factory)
    artifact_store = BoardArtifactStore(factory)
    board_service = BoardService(store)
    content_store = BoardArtifactContentStore(tmp_path / "artifacts")
    store.create_workflow(_WORKFLOW)
    service = ArtifactsService(
        store, artifact_store, board_service, content_store
    )
    return service, store, artifact_store


def _card(card_id: str, **overrides: object) -> WorkCard:
    fields: dict[str, object] = {
        "id": card_id,
        "workflow_id": "wf-1",
        "kind": "analysis",
        "title": card_id,
        "state": "review",
    }
    fields.update(overrides)
    return WorkCard(**fields)


def _artifact(**overrides: object) -> HandoffArtifact:
    fields: dict[str, object] = {
        "id": "artifact-1",
        "producer_card_id": "card-1",
        "logical_name": "report",
        "revision": 1,
        "content_ref": "file:///tmp/report.md",
        "content_hash": "sha256:abc",
        "trust": "agent_output",
    }
    fields.update(overrides)
    return HandoffArtifact(**fields)


class TestResultAcceptance:
    """Accepting a card's result records its artifact and completes it."""

    def test_accepting_a_result_moves_the_card_to_done(
        self, tmp_path: Path
    ) -> None:
        service, store, _artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))

        card = service.accept_result("card-1", _artifact())

        assert card.state == "done"
        assert store.get_card("card-1").state == "done"

    def test_the_artifact_is_durably_recorded(self, tmp_path: Path) -> None:
        service, store, artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))

        service.accept_result("card-1", _artifact())

        recorded = artifacts.list_for_card("card-1")
        assert [a.id for a in recorded] == ["artifact-1"]


class TestDependencyCascade:
    """A dependent card becomes ready once every dependency is done."""

    def test_waiting_dependent_becomes_ready_once_dependency_is_done(
        self, tmp_path: Path
    ) -> None:
        service, store, _artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        store.create_card(_card("card-2", state="waiting_dependency"))
        store.add_relation(CardRelation("card-2", "card-1"))

        service.accept_result("card-1", _artifact())

        assert store.get_card("card-2").state == "ready"

    def test_dependent_with_a_still_pending_sibling_dependency_stays_waiting(
        self, tmp_path: Path
    ) -> None:
        service, store, _artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        store.create_card(_card("card-1b"))
        store.create_card(_card("card-2", state="waiting_dependency"))
        store.add_relation(CardRelation("card-2", "card-1"))
        store.add_relation(CardRelation("card-2", "card-1b"))

        service.accept_result("card-1", _artifact())

        assert store.get_card("card-2").state == "waiting_dependency"


class TestReconciliation:
    """Conflicting sibling outputs create a reconciliation card, not an
    overwrite (FR-026)."""

    def test_conflicting_logical_names_create_a_reconciliation_card(
        self, tmp_path: Path
    ) -> None:
        service, store, _artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        store.create_card(_card("card-2"))
        service.accept_result(
            "card-1", _artifact(id="artifact-1", producer_card_id="card-1")
        )

        service.accept_result(
            "card-2",
            _artifact(
                id="artifact-2",
                producer_card_id="card-2",
                content_hash="sha256:different",
            ),
        )

        relations = store.list_relations("wf-1")
        reconciliation_targets = {
            r.depends_on_card_id
            for r in relations
            if r.kind == "reconciliation"
        }
        assert reconciliation_targets == {"card-1", "card-2"}

    def test_conflicting_result_does_not_overwrite_the_prior_artifact(
        self, tmp_path: Path
    ) -> None:
        service, store, artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        store.create_card(_card("card-2"))
        service.accept_result(
            "card-1", _artifact(id="artifact-1", producer_card_id="card-1")
        )

        service.accept_result(
            "card-2",
            _artifact(
                id="artifact-2",
                producer_card_id="card-2",
                content_hash="sha256:different",
            ),
        )

        assert artifacts.get("artifact-1").content_hash == "sha256:abc"
        assert artifacts.get("artifact-2").content_hash == "sha256:different"

    def test_matching_outputs_do_not_create_a_reconciliation_card(
        self, tmp_path: Path
    ) -> None:
        service, store, _artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        store.create_card(_card("card-2"))
        service.accept_result(
            "card-1", _artifact(id="artifact-1", producer_card_id="card-1")
        )

        service.accept_result(
            "card-2", _artifact(id="artifact-2", producer_card_id="card-2")
        )

        relations = store.list_relations("wf-1")
        assert not any(r.kind == "reconciliation" for r in relations)

    def test_different_logical_names_do_not_conflict(
        self, tmp_path: Path
    ) -> None:
        service, store, _artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        store.create_card(_card("card-2"))
        service.accept_result(
            "card-1", _artifact(id="artifact-1", producer_card_id="card-1")
        )

        service.accept_result(
            "card-2",
            _artifact(
                id="artifact-2",
                producer_card_id="card-2",
                logical_name="summary",
                content_hash="sha256:different",
            ),
        )

        relations = store.list_relations("wf-1")
        assert not any(r.kind == "reconciliation" for r in relations)


class TestSubmitResult:
    """``submit_result`` durably stores its content before accepting it."""

    def test_content_is_durably_stored_and_hash_matches(
        self, tmp_path: Path
    ) -> None:
        service, store, artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))

        card = service.submit_result(
            ArtifactDraft(
                producer_card_id="card-1",
                logical_name="report",
                revision=1,
                content="the actual result body",
                trust="agent_output",
            )
        )

        assert card.state == "done"
        recorded = artifacts.list_for_card("card-1")[0]
        expected_hash = hashlib.sha256(
            b"the actual result body"
        ).hexdigest()
        assert recorded.content_hash == expected_hash

    def test_stored_content_is_readable_back_through_the_ref(
        self, tmp_path: Path
    ) -> None:
        service, store, artifacts = _service(tmp_path)
        store.create_card(_card("card-1"))
        content_store = BoardArtifactContentStore(tmp_path / "artifacts")

        service.submit_result(
            ArtifactDraft(
                producer_card_id="card-1",
                logical_name="report",
                revision=1,
                content="the actual result body",
                trust="agent_output",
            )
        )

        recorded = artifacts.list_for_card("card-1")[0]
        assert content_store.read(recorded.content_ref) == (
            "the actual result body"
        )

    def test_no_content_store_configured_raises(self, tmp_path: Path) -> None:
        factory = _factory(tmp_path)
        store = BoardStore(factory)
        artifact_store = BoardArtifactStore(factory)
        board_service = BoardService(store)
        store.create_workflow(_WORKFLOW)
        store.create_card(_card("card-1"))
        service = ArtifactsService(store, artifact_store, board_service)

        with pytest.raises(ValueError, match="content store"):
            service.submit_result(
                ArtifactDraft(
                    producer_card_id="card-1",
                    logical_name="report",
                    revision=1,
                    content="x",
                    trust="agent_output",
                )
            )
