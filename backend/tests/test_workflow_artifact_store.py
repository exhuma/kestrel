"""Tests for durable workflow-owned artifact records."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models_workflow import WorkflowArtifact, WorkflowRun
from app.persistence.workflow_artifact_store import WorkflowArtifactStore
from app.persistence.workflow_store import WorkflowStore


def _factory(tmp_path: Path) -> sessionmaker:
    """Return a session factory for an isolated, migrated SQLite database."""
    database = tmp_path / "artifacts.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    return sessionmaker(bind=sa.create_engine(f"sqlite:///{database}"))


def _store(tmp_path: Path) -> WorkflowArtifactStore:
    """Create an artifact store with an owning workflow row."""
    factory = _factory(tmp_path)
    WorkflowStore(factory).save(WorkflowRun(id="wf-1", repo="owner/repo"))
    return WorkflowArtifactStore(factory)


def test_recorded_artifact_round_trips(tmp_path: Path) -> None:
    """An artifact retains its cleanup metadata and allocated id."""
    store = _store(tmp_path)
    artifact = store.record(
        WorkflowArtifact(
            workflow_id="wf-1",
            kind="remote_branch",
            external_id="kestrel/issue-7",
            display_name="kestrel/issue-7",
            cleanup_mode="required_remove",
        )
    )

    assert artifact.id is not None
    assert artifact.created_at is not None
    assert store.list_for("wf-1") == [artifact]


def test_failed_artifact_is_retained_while_resolved_artifact_is_pruned(
    tmp_path: Path,
) -> None:
    """Cleanup finalization keeps retryable failures but drops resolutions."""
    store = _store(tmp_path)
    resolved = store.record(
        WorkflowArtifact("wf-1", "workspace", "/tmp/wf-1", "wf-1", "remove")
    )
    failed = store.record(
        WorkflowArtifact("wf-1", "comment", "42", "comment 42", "best_effort")
    )
    assert resolved.id is not None
    assert failed.id is not None

    store.set_state(resolved.id, "absent")
    store.set_state(failed.id, "failed", "provider unavailable")
    store.discard_resolved("wf-1")

    assert store.list_for("wf-1") == [
        WorkflowArtifact(
            id=failed.id,
            workflow_id="wf-1",
            kind="comment",
            external_id="42",
            display_name="comment 42",
            cleanup_mode="best_effort",
            state="failed",
            error="provider unavailable",
            created_at=failed.created_at,
        )
    ]
