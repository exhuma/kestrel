"""Immutable artifact provenance and project-material selection tests
(feature 026).

Exercises ``app.persistence.board_artifact_store.BoardArtifactStore``
against a real, migrated SQLite database.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models_board import WorkCard, Workflow
from app.models_board_records import HandoffArtifact
from app.persistence.board_artifact_store import (
    BoardArtifactStore,
    DuplicateArtifactError,
)
from app.persistence.board_store import BoardStore
from tests.board_test_support import board_session_factory


def _seeded(tmp_path: Path) -> tuple[BoardStore, BoardArtifactStore]:
    """A board with one workflow and one card, plus an artifact store."""
    factory = board_session_factory(tmp_path)
    board = BoardStore(factory)
    board.create_workflow(
        Workflow(
            id="wf-1",
            source="github-issue",
            task_ref="owner/repo#1",
            repo="owner/repo",
            base_branch="main",
            source_visibility="public",
            title="Add a thing",
        )
    )
    board.create_card(
        WorkCard(
            id="card-1",
            workflow_id="wf-1",
            kind="analysis",
            title="Investigate",
            state="ready",
            eligible_roles=("developer",),
        )
    )
    return board, BoardArtifactStore(factory)


def _artifact(**overrides: object) -> HandoffArtifact:
    """A minimal valid artifact, with any field overridden."""
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


class TestArtifactProvenance:
    """A recorded artifact retains immutable identity and provenance."""

    def test_record_and_read_round_trips(self, tmp_path: Path) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifact = artifacts.record(_artifact())
        fetched = artifacts.get("artifact-1")
        assert fetched == artifact
        assert fetched.producer_card_id == "card-1"
        assert fetched.logical_name == "report"
        assert fetched.revision == 1

    def test_duplicate_revision_is_rejected(self, tmp_path: Path) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifacts.record(_artifact())
        with pytest.raises(DuplicateArtifactError):
            artifacts.record(
                _artifact(id="artifact-2", content_hash="sha256:def")
            )

    def test_a_new_revision_of_the_same_logical_name_is_allowed(
        self, tmp_path: Path
    ) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifacts.record(_artifact())
        next_revision = 2
        second = artifacts.record(
            _artifact(id="artifact-2", revision=next_revision)
        )
        assert second.revision == next_revision

    def test_records_exact_consumed_input_artifact_ids(
        self, tmp_path: Path
    ) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifacts.record(_artifact())
        derived = artifacts.record(
            _artifact(
                id="artifact-2",
                logical_name="summary",
                content_ref="file:///tmp/summary.md",
                content_hash="sha256:xyz",
                input_artifacts=("artifact-1",),
            )
        )
        assert artifacts.get(derived.id).input_artifacts == ("artifact-1",)


class TestProjectMaterialSelection:
    """Only explicitly material artifacts are selected for project delivery."""

    def test_default_artifact_is_not_project_material(
        self, tmp_path: Path
    ) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifacts.record(_artifact(logical_name="notes"))
        assert artifacts.project_material_for_workflow("wf-1") == ()

    def test_explicit_material_artifact_is_selected(
        self, tmp_path: Path
    ) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifacts.record(
            _artifact(logical_name="patch", project_material=True)
        )
        selected = artifacts.project_material_for_workflow("wf-1")
        assert [a.id for a in selected] == ["artifact-1"]

    def test_mixed_artifacts_select_only_the_material_ones(
        self, tmp_path: Path
    ) -> None:
        _board, artifacts = _seeded(tmp_path)
        artifacts.record(
            _artifact(logical_name="notes", project_material=False)
        )
        artifacts.record(
            _artifact(
                id="artifact-2",
                logical_name="patch",
                content_hash="sha256:def",
                project_material=True,
            )
        )
        selected = artifacts.project_material_for_workflow("wf-1")
        assert [a.id for a in selected] == ["artifact-2"]
