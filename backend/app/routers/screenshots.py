"""HTTP routes serving a workflow run's screenshots (gallery + image bytes).

A separate router from ``workflows.py`` (keeping that module under the
line cap). Images are read from the shared worktree, or the durable copy
once the run's worktree has been torn down — see
``services/workflows/screenshots.py``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.models_workflow import WorkflowRun
from app.schemas import ScreenshotOut
from app.services.workflows import WorkflowService, get_workflow_service
from app.services.workflows import screenshots as shots

router = APIRouter(prefix="/api/workflows")


def _url(run: WorkflowRun, stage: str, name: str) -> str:
    return f"/api/workflows/{run.id}/screenshots/{stage}/{name}"


@router.get("/{workflow_id}/screenshots", response_model=list[ScreenshotOut])
async def list_workflow_screenshots(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
    settings: Settings = Depends(get_settings),
) -> list[ScreenshotOut]:
    """List a run's screenshots (refine mockups first, then verify shots)."""
    run = service.get(workflow_id)  # 404 on unknown run
    return [
        ScreenshotOut(
            name=s.name, stage=s.stage, url=_url(run, s.stage, s.name)
        )
        for s in shots.list_screenshots(run, settings.screenshots_root)
    ]


@router.get("/{workflow_id}/screenshots/{stage}/{name}")
async def get_workflow_screenshot(
    workflow_id: str,
    stage: str,
    name: str,
    service: WorkflowService = Depends(get_workflow_service),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    """Serve one screenshot's bytes.

    404 on an unknown run, an unknown stage, a path-traversal attempt, a
    non-image name, a missing file, or an oversized file — every invalid
    case collapses to ``resolve_path`` returning ``None``.
    """
    run = service.get(workflow_id)  # 404 on unknown run
    path = shots.resolve_path(run, stage, name, settings.screenshots_root)
    if path is None:
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(path, media_type=shots.mime_for(name))
