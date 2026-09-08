"""GitHub webhook ingress — the one endpoint reachable off-loopback.

HMAC verification of ``X-Hub-Signature-256`` is the authenticity gate
(constitution v1.2.0). The secret and signature are never logged
(FR-006). Run creation is dispatched to a background task so the ACK is
never blocked on it (FR-005).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.persistence.dismissal_store import DismissalStore, get_dismissal_store
from app.persistence.webhook_delivery_store import (
    WebhookDeliveryStore,
    get_webhook_delivery_store,
)
from app.services.feedback import github_events
from app.services.feedback.intake import (
    FeedbackIntakeService,
    get_feedback_intake_service,
)
from app.services.github import GitHubCodeHost
from app.services.github_tasksource import GitHubTaskSource
from app.services.ingestion import IngestionService, get_ingestion_service

#: Webhook events this router intakes feedback from, mapped to the
#: ``github_events`` handler that builds+dispatches the Feedback. Kept as
#: a table (not an if/elif chain) so the route function's own branching
#: stays flat regardless of how many review-origin event types exist.
_FEEDBACK_EVENT_HANDLERS = {
    "pull_request_review": github_events.handle_pull_request_review,
    "pull_request_review_comment": (
        github_events.handle_pull_request_review_comment
    ),
}

router = APIRouter(prefix="/api/github")

_log = logging.getLogger("kestrel.webhook")

#: Keep background run-start tasks referenced so they are not GC'd mid-flight.
_TASKS: set[asyncio.Task] = set()


async def verify_signature(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Reject a delivery whose HMAC signature is missing or invalid.

    Verifies ``sha256=<hex>`` of the raw body under ``webhook_secret`` with
    a constant-time comparison (FR-002/FR-003). An empty secret rejects
    every delivery (the webhook path is disabled). The secret/signature are
    never included in the error.

    :raises HTTPException: 401 when the signature is missing or invalid.
    """
    secret = settings.webhook_secret
    sig = request.headers.get("X-Hub-Signature-256", "")
    body = await request.body()
    if not secret or not sig:
        raise HTTPException(status_code=401, detail="missing signature")
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={digest}", sig):
        raise HTTPException(status_code=401, detail="invalid signature")


def _fire_and_forget(coro) -> None:
    """Run ``coro`` in the background, kept referenced so it is not GC'd
    mid-flight; any failure is the coroutine's own responsibility to log
    (the caller's ACK has already been sent)."""
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _dispatch_start(
    ingestion: IngestionService, repo: str, issue_number: int
) -> None:
    """Fire-and-forget a run start; a failure is logged, never surfaced."""

    async def _run() -> None:
        try:
            await ingestion.maybe_start_run(
                source="github-issue",
                task_ref=f"{repo}#{issue_number}",
                code_repo=repo,
                issue_number=issue_number,
            )
        except Exception:  # noqa: BLE001 — best-effort; ACK already sent
            _log.exception(
                "webhook run-failed %s#%s", repo, issue_number
            )

    _fire_and_forget(_run())


def _dispatch_feedback_intake(
    payload: dict,
    settings: Settings,
    intake: FeedbackIntakeService,
    source: GitHubTaskSource,
) -> None:
    """Fire-and-forget the feedback pipeline for one ``issue_comment``."""

    async def _run() -> None:
        try:
            await github_events.handle_issue_comment(
                payload, settings, intake, source
            )
        except Exception:  # noqa: BLE001 — best-effort; ACK already sent
            _log.exception("webhook feedback-intake failed")

    _fire_and_forget(_run())


def _dispatch_review_feedback_intake(
    event: str,
    payload: dict,
    settings: Settings,
    intake: FeedbackIntakeService,
    code_host: GitHubCodeHost,
) -> None:
    """Fire-and-forget the feedback pipeline for a review-origin event
    (feature 013, US3 — ``pull_request_review``/
    ``pull_request_review_comment``)."""
    handler = _FEEDBACK_EVENT_HANDLERS[event]

    async def _run() -> None:
        try:
            await handler(payload, settings, intake, code_host)
        except Exception:  # noqa: BLE001 — best-effort; ACK already sent
            _log.exception("webhook review-feedback-intake failed")

    _fire_and_forget(_run())


@dataclass
class _FeedbackAdapters:
    """The two GitHub adapters feedback intake acknowledges through —
    bundled behind one dependency so ``_webhook_deps`` stays under the
    arg-count limit as this grows (feature 013, US3 added the second)."""

    source: GitHubTaskSource
    codehost: GitHubCodeHost


def _feedback_adapters(
    source: GitHubTaskSource = Depends(
        github_events.get_feedback_github_source
    ),
    codehost: GitHubCodeHost = Depends(
        github_events.get_feedback_github_codehost
    ),
) -> _FeedbackAdapters:
    return _FeedbackAdapters(source, codehost)


@dataclass
class _WebhookDeps:
    """Bundles the webhook route's per-request dependencies (keeps the
    route function itself under the arg-count limit)."""

    deliveries: WebhookDeliveryStore
    dismissals: DismissalStore
    ingestion: IngestionService
    intake: FeedbackIntakeService
    feedback: _FeedbackAdapters


def _webhook_deps(
    deliveries: WebhookDeliveryStore = Depends(get_webhook_delivery_store),
    dismissals: DismissalStore = Depends(get_dismissal_store),
    ingestion: IngestionService = Depends(get_ingestion_service),
    intake: FeedbackIntakeService = Depends(get_feedback_intake_service),
    feedback: _FeedbackAdapters = Depends(_feedback_adapters),
) -> _WebhookDeps:
    return _WebhookDeps(deliveries, dismissals, ingestion, intake, feedback)


@router.post("/webhook", dependencies=[Depends(verify_signature)])
async def github_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    deps: _WebhookDeps = Depends(_webhook_deps),
) -> JSONResponse:
    """
    Accept a GitHub webhook and, if qualifying, start a run or intake
    feedback.

    Order: signature (dependency) → parse → event/action/label/repo gating
    → dismissal → dedup → dispatch. Authentic-but-non-triggering deliveries
    are acknowledged with 200 so GitHub stops retrying (FR-011); a
    qualifying delivery returns 202 with the work dispatched in the
    background (FR-005; feature 013 for ``issue_comment``).
    """
    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")
    if not event or not delivery:
        raise HTTPException(status_code=400, detail="missing webhook headers")
    try:
        payload = await request.json()
    except Exception as exc:  # malformed body — acknowledge, don't crash
        raise HTTPException(
            status_code=400, detail="malformed payload"
        ) from exc

    def _ack(status: int, outcome: str, issue: int | None) -> JSONResponse:
        deps.deliveries.seen(delivery, event, outcome, repo, issue)
        _log.info(
            "webhook delivery=%s event=%s action=%s repo=%s issue=%s "
            "outcome=%s",
            delivery, event, payload.get("action"), repo, issue, outcome,
        )
        return JSONResponse(status_code=status, content={"status": outcome})

    repo = (payload.get("repository") or {}).get("full_name")
    action = payload.get("action")
    issue_number = (payload.get("issue") or {}).get("number")
    label = (payload.get("label") or {}).get("name")

    if event == "issue_comment":
        if not github_events.is_qualifying_comment(payload, settings):
            return _ack(200, "ignored", issue_number)
        _dispatch_feedback_intake(
            payload, settings, deps.intake, deps.feedback.source
        )
        return _ack(202, "accepted", issue_number)

    if event in _FEEDBACK_EVENT_HANDLERS:
        pr_number = (payload.get("pull_request") or {}).get("number")
        if not github_events.is_qualifying_pr_event(payload, settings):
            return _ack(200, "ignored", pr_number)
        _dispatch_review_feedback_intake(
            event, payload, settings, deps.intake, deps.feedback.codehost
        )
        return _ack(202, "accepted", pr_number)

    def _handle_issues_event() -> JSONResponse:
        """The ``issues`` (label-trigger) event's own gate/dedup chain —
        nested so it shares ``_ack``/the parsed payload fields via
        closure instead of a long parameter list, and so the outer
        route function's own branch count stays under the guardrail."""
        gh_source = settings.github_source_for(repo) if repo else None
        watched = gh_source is not None
        is_trigger = (
            gh_source is not None and label == gh_source.trigger_label
        )
        # Label removed: clear any dismissal so a re-label starts fresh.
        if action == "unlabeled":
            if watched and is_trigger and issue_number is not None:
                deps.dismissals.clear(f"{repo}#{issue_number}")
            return _ack(200, "ignored", issue_number)
        if action != "labeled" or not is_trigger or not watched:
            return _ack(200, "ignored", issue_number)
        if issue_number is None:
            return _ack(400, "ignored", None)
        if deps.dismissals.is_dismissed(f"{repo}#{issue_number}"):
            return _ack(200, "ignored", issue_number)
        # Dedup: record and check at-most-once. A re-delivery is
        # acknowledged without starting a second run (FR-004).
        if deps.deliveries.seen(
            delivery, event, "accepted", repo, issue_number
        ):
            _log.info(
                "webhook delivery=%s repo=%s issue=%s outcome=duplicate",
                delivery, repo, issue_number,
            )
            return JSONResponse(
                status_code=200, content={"status": "duplicate"}
            )
        _dispatch_start(deps.ingestion, repo, issue_number)
        _log.info(
            "webhook delivery=%s repo=%s issue=%s outcome=accepted",
            delivery, repo, issue_number,
        )
        return JSONResponse(status_code=202, content={"status": "accepted"})

    if event != "issues":
        return _ack(200, "ignored", issue_number)
    return _handle_issues_event()
