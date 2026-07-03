"""HTTP routes for GitHub issue -> code workflows."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.models_workflow import WorkflowRun
from app.schemas import (
    AnswersIn,
    ApproveIn,
    CreateWorkflowIn,
    RejectIn,
    ReplyIn,
    WorkflowDetail,
    WorkflowStepOut,
    WorkflowSummary,
)
from app.services.workflows import WorkflowService, get_workflow_service

router = APIRouter(prefix="/api/workflows")


def _detail(service: WorkflowService, run: WorkflowRun) -> WorkflowDetail:
    return WorkflowDetail(
        id=run.id,
        repo=run.repo,
        issue_number=run.issue_number,
        issue_title=run.issue_title,
        status=run.status,
        branch=run.branch,
        steps=[
            WorkflowStepOut(
                name=s.name, session_id=s.session_id,
                status=s.status, deliverable=s.deliverable,
            )
            for s in run.steps
        ],
        current_session_id=service.current_session_id(run),
        pr_url=run.pr_url,
        error=run.error,
    )


@router.post("")
async def create_workflow(
    body: CreateWorkflowIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Start a workflow and return its id."""
    wid = await service.create(body.repo, body.issue_number)
    return {"workflow_id": wid}


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(
    service: WorkflowService = Depends(get_workflow_service),
) -> list[WorkflowSummary]:
    """List all workflow runs."""
    return [
        WorkflowSummary(
            id=r.id, repo=r.repo, issue_number=r.issue_number, status=r.status
        )
        for r in service.list()
    ]


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowDetail:
    """Return a workflow's full detail."""
    return _detail(service, service.get(workflow_id))


@router.post("/{workflow_id}/reply")
async def reply_workflow(
    workflow_id: str,
    body: ReplyIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Answer the refine interview."""
    service.reply(workflow_id, body.text)
    return {"status": "ok"}


@router.post("/{workflow_id}/approve")
async def approve_workflow(
    workflow_id: str,
    body: ApproveIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Approve the current gate (optionally with an edited deliverable)."""
    service.approve(workflow_id, body.deliverable)
    return {"status": "ok"}


@router.post("/{workflow_id}/reject")
async def reject_workflow(
    workflow_id: str,
    body: RejectIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Reject the current gate, optionally with feedback."""
    service.reject(workflow_id, body.refinement_prompt)
    return {"status": "ok"}


@router.post("/{workflow_id}/answers/draft")
async def save_draft_answers(
    workflow_id: str,
    body: AnswersIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Persist a partial answer set without finalizing the interview."""
    service.save_draft(workflow_id, body.answers)
    return {"status": "ok"}


@router.post("/{workflow_id}/answers")
async def submit_answers(
    workflow_id: str,
    body: AnswersIn,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Finalize the pending questionnaire (all questions answered/waived)."""
    service.submit_answers(workflow_id, body.answers)
    return {"status": "ok"}
