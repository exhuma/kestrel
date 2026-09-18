"""Artifact-ledger methods mixed into the workflow service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from app.documents import Document
from app.models_workflow import WorkflowArtifact, WorkflowRun

if TYPE_CHECKING:
    from app.persistence.workflow_artifact_store import WorkflowArtifactStore
    from app.ports import TaskSource


class _ArtifactOwner(Protocol):
    """Minimal workflow-service surface required by artifact helpers."""

    artifact_store: "WorkflowArtifactStore | None"

    def _task_source(self, run: WorkflowRun) -> "TaskSource":
        """Return the task source bound to ``run``."""
        ...


class WorkflowArtifactService:
    """Provides durable, workflow-owned artifact recording and comments."""

    def record_artifact(
        self,
        run: WorkflowRun,
        kind: str,
        external_id: str,
        display_name: str,
        cleanup_mode: str = "required_remove",
    ) -> None:
        """Record a Kestrel-owned resource after its creation succeeds."""
        owner = cast(_ArtifactOwner, self)
        if owner.artifact_store is not None:
            owner.artifact_store.record(
                WorkflowArtifact(
                    workflow_id=run.id,
                    kind=kind,
                    external_id=external_id,
                    display_name=display_name,
                    cleanup_mode=cleanup_mode,
                )
            )

    def artifacts(self, workflow_id: str) -> list[WorkflowArtifact]:
        """Return currently tracked cleanup resources for ``workflow_id``."""
        owner = cast(_ArtifactOwner, self)
        if owner.artifact_store is None:
            return []
        return owner.artifact_store.list_for(workflow_id)

    async def post_comment(
        self, run: WorkflowRun, body: Document | str, display_name: str
    ) -> str:
        """Post and record a Kestrel-owned source comment for cleanup.

        A successful post must provide its source-native identifier. Without
        one, later recovery could not distinguish a completed post from a
        missing one, so this raises instead of allowing the workflow to
        complete with an unconfirmed mandatory comment.
        """
        owner = cast(_ArtifactOwner, self)
        comment = await owner._task_source(run).post_comment(run.task_ref, body)
        if not comment:
            raise RuntimeError(
                f"source did not confirm {display_name} publication"
            )
        self.record_artifact(
            run, "comment", comment, display_name, "best_effort"
        )
        return comment
