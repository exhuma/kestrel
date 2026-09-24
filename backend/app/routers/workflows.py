"""HTTP routes for GitHub issue -> code workflows."""
from __future__ import annotations

import json
from typing import AsyncIterator, cast

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app import documents, sse
from app.config import get_settings
from app.documents_json import document_json, parse_document_json
from app.models_workflow import (
    Step,
    WorkflowArtifact,
    WorkflowRun,
    WorkflowStep,
)
from app.policy import label_policy
from app.questionnaire import parse_envelope
from app.routers.workflow_gate_screening import answers_text, screen_gate_input
from app.schemas import (
    AnswersIn,
    ApproveIn,
    RejectIn,
    ReplyIn,
    RoundChipOut,
    StepSessionOut,
    WorkflowArtifactOut,
    WorkflowDetail,
    WorkflowStepOut,
    WorkflowSummary,
)
from app.services.board.bootstrap import get_quarantine_service
from app.services.board.quarantine import QuarantineService
from app.services.workflows import (
    MAX_REFINE_ROUNDS,
    MAX_REFINE_ROUNDS_HARD,
    WorkflowService,
    get_workflow_service,
)
from app.storage.workflow_bus import WorkflowBus, get_workflow_bus

router = APIRouter(prefix="/api/workflows")


def _step_out(
    s: WorkflowStep, policy: object
) -> WorkflowStepOut:
    """Build a single :class:`WorkflowStepOut` with the correct format.

    The code step renders as a git diff; the technical-analysis step
    renders as a structured document; everything else falls through to
    markdown.
    """
    name = s.name
    deliverable = s.deliverable
    doc = _ta_document(name, deliverable)
    if name == Step.CODE:
        fmt = "diff"
    elif doc is not None:
        fmt = "document"
    else:
        fmt = "markdown"
    return WorkflowStepOut(
        name=name,
        session_id=s.session_id,
        status=s.status,
        deliverable=json.dumps(doc) if doc is not None else deliverable,
        refine_round=s.refine_round,
        verify_round=s.verify_round,
        backend=policy.backend_id_for(name),  # type: ignore[union-attr]
        deliverable_format=fmt,
    )


def _ta_document(step_name: str, deliverable: str | None) -> dict | None:
    """Render the technical-analysis candidate as a UI document payload.

    Returns ``None`` when the step is not technical_analysis or the
    deliverable is not a valid candidate JSON blob. Otherwise returns the
    output of :func:`app.documents_json.document_json` for the stored analysis
    document followed by a structured task list, so the frontend can render
    it as a structured document instead of raw JSON text.

    The analysis is already stored in closed JSON form (serialized at the
    LLM boundary by the driver), so this only deserializes — no Markdown
    parsing happens here.
    """
    if step_name != Step.TECHNICAL_ANALYSIS or not deliverable:
        return None
    try:
        payload = json.loads(deliverable)
        analysis_raw = payload["technical_analysis"]
        if not isinstance(analysis_raw, dict):
            return None
        tasks = payload.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    try:
        doc = parse_document_json(analysis_raw)
    except ValueError:
        return None
    task_blocks = _task_list_blocks(tasks)
    combined = documents.Document(doc.blocks + task_blocks)
    return document_json(combined)


def _task_list_blocks(
    tasks: list[dict[str, object]],
) -> tuple[documents.Block, ...]:
    """Build document blocks for the proposed child-task section.

    Each task is rendered as a heading followed by its body content (parsed
    from markdown at this API boundary). Task bodies are markdown strings
    owned by the LLM; they are parsed here so the frontend can render them
    as structured document blocks.
    """
    if not tasks:
        return ()
    blocks: list[documents.Block] = [
        documents.Heading(2, (documents.Text("Proposed child tasks"),))
    ]
    for task in tasks:
        title = str(task.get("title", ""))
        effort = task.get("effort_man_days")
        model_id = task.get("recommended_model_id")
        meta: list[str] = []
        if isinstance(effort, (int, float)):
            meta.append(f"{effort:g}d")
        if model_id:
            meta.append(str(model_id))
        label = title if not meta else f"{title} ({', '.join(meta)})"
        blocks.append(
            documents.Heading(3, (documents.Text(label),))
        )
        body = str(task.get("body", ""))
        if body:
            blocks.extend(documents.parse_markdown(body).blocks)
    return tuple(blocks)


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
            _step_out(s, policy)
            for s in run.steps
        ],
        current_session_id=service.current_session_id(run),
        active_sessions=active_sessions,
        round_history=[
            RoundChipOut(
                step=c.step, round_index=c.round_index,
                profile_id=c.profile_id, label=c.label, badge=c.badge,
                session_id=c.session_id, status=c.status, error=c.error,
                retired_at=c.retired_at,
            )
            for c in service.round_history(run.id)
        ],
        refine_round_cap=round_cap,
        refine_max_rounds=MAX_REFINE_ROUNDS_HARD,
        verify_max_iterations=get_settings().max_verify_iterations,
        allow_incomplete_answers=get_settings().allow_incomplete_answers,
        rerunnable=service.rerunnable(run),
        task_label=service.task_label(run),
        task_link=service.task_link(run),
        pr_url=run.pr_url,
        error=run.error,
        artifacts=[
            WorkflowArtifactOut(
                kind=artifact.kind,
                display_name=artifact.display_name,
                cleanup_mode=artifact.cleanup_mode,
                state=artifact.state,
                error=artifact.error,
            )
            for artifact in _artifacts(service, run.id)
        ],
    )


def _artifacts(
    service: WorkflowService, workflow_id: str
) -> list[WorkflowArtifact]:
    """Return artifact records, preserving lightweight router test doubles."""
    artifacts = getattr(service, "artifacts", None)
    if artifacts is None:
        return []
    return cast(list[WorkflowArtifact], artifacts(workflow_id))


def _summaries(service: WorkflowService) -> list[WorkflowSummary]:
    return [
        WorkflowSummary(
            id=r.id,
            repo=r.repo,
            issue_number=r.issue_number,
            status=r.status,
            rerunnable=service.rerunnable(r),
            task_label=service.task_label(r),
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


@router.post("/{workflow_id}/poll", response_model=WorkflowDetail)
async def poll_workflow_step(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowDetail:
    """Actively probe the run's live chips against their backend."""
    await service.poll_active_step(workflow_id)
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


@router.post("/{workflow_id}/cleanup")
async def cleanup_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """
    Fully reset a workflow: drop local work, delete its branch (local
    mirror and remote), and clear its dismissal so the next poll picks
    the underlying task up as a brand-new workflow.
    """
    await service.cleanup(workflow_id)
    return {"status": "ok"}


@router.post("/{workflow_id}/rerun")
async def rerun_workflow(
    workflow_id: str,
    service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, str]:
    """
    Discard a run and immediately start a fresh one for the same task.

    Refused with HTTP 403 unless the run's task source is private
    (feature 008) — never available for a GitHub/Jira-sourced run.
    """
    new_id = await service.rerun(workflow_id)
    return {"workflow_id": new_id}


@router.post("/{workflow_id}/reply")
async def reply_workflow(
    workflow_id: str,
    body: ReplyIn,
    service: WorkflowService = Depends(get_workflow_service),
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> dict[str, object]:
    """Answer the refine interview."""
    blocked = await screen_gate_input(
        quarantine, workflow_id, "gate_reply", body.text
    )
    if blocked is not None:
        return blocked
    service.reply(workflow_id, body.text)
    return {"status": "ok"}


@router.post("/{workflow_id}/approve")
async def approve_workflow(
    workflow_id: str,
    body: ApproveIn,
    service: WorkflowService = Depends(get_workflow_service),
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> dict[str, object]:
    """Approve the current gate (optionally with an edited deliverable)."""
    blocked = await screen_gate_input(
        quarantine, workflow_id, "gate_approval_edit", body.deliverable or ""
    )
    if blocked is not None:
        return blocked
    service.approve(workflow_id, body.deliverable)
    return {"status": "ok"}


@router.post("/{workflow_id}/reject")
async def reject_workflow(
    workflow_id: str,
    body: RejectIn,
    service: WorkflowService = Depends(get_workflow_service),
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> dict[str, object]:
    """Reject the current gate, optionally with feedback."""
    blocked = await screen_gate_input(
        quarantine,
        workflow_id,
        "gate_rejection_feedback",
        body.refinement_prompt or "",
    )
    if blocked is not None:
        return blocked
    service.reject(workflow_id, body.refinement_prompt)
    return {"status": "ok"}


@router.post("/{workflow_id}/answers/draft")
async def save_draft_answers(
    workflow_id: str,
    body: AnswersIn,
    service: WorkflowService = Depends(get_workflow_service),
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> dict[str, object]:
    """Persist a partial answer set without finalizing the interview."""
    blocked = await screen_gate_input(
        quarantine,
        workflow_id,
        "questionnaire_draft",
        answers_text(body.answers),
    )
    if blocked is not None:
        return blocked
    service.save_draft(workflow_id, body.answers)
    return {"status": "ok"}


@router.post("/{workflow_id}/answers")
async def submit_answers(
    workflow_id: str,
    body: AnswersIn,
    service: WorkflowService = Depends(get_workflow_service),
    quarantine: QuarantineService = Depends(get_quarantine_service),
) -> dict[str, object]:
    """Finalize the pending questionnaire (all questions answered/waived)."""
    blocked = await screen_gate_input(
        quarantine,
        workflow_id,
        "questionnaire_answers",
        answers_text(body.answers),
    )
    if blocked is not None:
        return blocked
    service.submit_answers(workflow_id, body.answers)
    return {"status": "ok"}
