"""HTTP routes for GitHub issue -> code workflows."""
from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app import sse
from app.config import get_settings
from app.models_workflow import Step, WorkflowRun
from app.policy import label_policy
from app.questionnaire import parse_envelope
from app.schemas import (
    AnswersIn,
    ApproveIn,
    CreateWorkflowIn,
    RejectIn,
    ReplyIn,
    StepSessionOut,
    WorkflowDetail,
    WorkflowStepOut,
    WorkflowSummary,
)
from app.services.workflows import (
    MAX_REFINE_ROUNDS,
    MAX_REFINE_ROUNDS_HARD,
    WorkflowService,
    get_workflow_service,
)
from app.storage.workflow_bus import WorkflowBus, get_workflow_bus

router = APIRouter(prefix="/api/workflows")


def _detail(service: WorkflowService, run: WorkflowRun) -> WorkflowDetail:
    active = next(
        (
            s for s in run.steps
            if s.status in ("running", "awaiting_input", "awaiting_approval")
        ),
        None,
    )
    active_sessions = [
        StepSessionOut(
            profile_id=ss.profile_id, label=ss.label, badge=ss.badge,
            session_id=ss.session_id, status=ss.status, activity=ss.activity,
            error=ss.error,
        )
        for ss in (active.active_sessions if active else [])
    ]
    # Registry-free: labelling steps must not build the backend registry (which
    # would eagerly load the session store from the DB) — see label_policy().
    policy = label_policy()
    # The dynamic round cap lives in the refine step's interview envelope
    # (loop state), not a column; read it for the UI's "Round N / cap".
    refine = next((s for s in run.steps if s.name == Step.REFINE), None)
    envelope = parse_envelope(refine.deliverable or "") if refine else None
    round_cap = (
        envelope.round_cap if envelope is not None else MAX_REFINE_ROUNDS
    )
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
                refine_round=s.refine_round,
                verify_round=s.verify_round,
                backend=policy.backend_id_for(s.name),
                # The code step's deliverable is a raw git diff; everything
                # else is prose/questionnaire that renders as markdown.
                deliverable_format=(
                    "diff" if s.name == Step.CODE else "markdown"
                ),
            )
            for s in run.steps
        ],
        current_session_id=service.current_session_id(run),
        active_sessions=active_sessions,
        refine_round_cap=round_cap,
        refine_max_rounds=MAX_REFINE_ROUNDS_HARD,
        verify_max_iterations=get_settings().max_verify_iterations,
        allow_incomplete_answers=get_settings().allow_incomplete_answers,
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


def _summaries(service: WorkflowService) -> list[WorkflowSummary]:
    return [
        WorkflowSummary(
            id=r.id, repo=r.repo, issue_number=r.issue_number, status=r.status
        )
        for r in service.list()
    ]


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(
    service: WorkflowService = Depends(get_workflow_service),
) -> list[WorkflowSummary]:
    """List all workflow runs."""
    return _summaries(service)


@router.get("/events")
async def stream_workflows(
    service: WorkflowService = Depends(get_workflow_service),
    bus: WorkflowBus = Depends(get_workflow_bus),
) -> StreamingResponse:
    """
    Stream the workflow summary list as Server-Sent Events.

    Emits the current list immediately, then a fresh list on *any* run change
    — including creation — so the sidebar live-adds runs started by background
    ingestion (GitHub webhook / Jira poll), not only UI-created ones. Declared
    before ``/{workflow_id}`` so the static path is not captured as an id.
    """
    def _snapshot() -> bytes:
        return sse.encode(
            [s.model_dump(mode="json") for s in _summaries(service)]
        )

    async def _frames() -> AsyncIterator[bytes]:
        q = bus.subscribe_list()
        try:
            yield _snapshot()
            async for tick in sse.with_heartbeat(q):
                yield sse.KEEPALIVE if tick is None else _snapshot()
        finally:
            bus.unsubscribe_list(q)

    return StreamingResponse(
        _frames(), media_type="text/event-stream", headers=sse.HEADERS
    )


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowDetail:
    """Return a workflow's full detail."""
    return _detail(service, service.get(workflow_id))


@router.get("/{workflow_id}/events")
async def stream_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
    bus: WorkflowBus = Depends(get_workflow_bus),
) -> StreamingResponse:
    """
    Stream a workflow's full detail as Server-Sent Events.

    Emits the current snapshot immediately, then a fresh snapshot on
    every state change (status, step, deliverable, or session chips) —
    replacing the old fixed-interval poll. Validates the id up front so
    an unknown workflow is a clean 404 before streaming starts.
    """
    service.get(workflow_id)  # 404 before we start streaming

    def _snapshot() -> bytes:
        return sse.encode(
            _detail(service, service.get(workflow_id)).model_dump(mode="json")
        )

    async def _frames() -> AsyncIterator[bytes]:
        q = bus.subscribe(workflow_id)
        try:
            yield _snapshot()
            async for tick in sse.with_heartbeat(q):
                yield sse.KEEPALIVE if tick is None else _snapshot()
        finally:
            bus.unsubscribe(workflow_id, q)

    return StreamingResponse(
        _frames(), media_type="text/event-stream", headers=sse.HEADERS
    )


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """Abandon a workflow, dropping all local work (never touches GitHub)."""
    await service.delete(workflow_id)
    return {"status": "ok"}


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
