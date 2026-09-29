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
from app.services.ingestion import IngestionService, get_ingestion_service

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


async def _payload_from(request: Request) -> dict:
    """Parse a GitHub JSON payload or raise the webhook's 400 error."""
    try:
        return await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="malformed payload"
        ) from exc


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


@dataclass
class _WebhookDeps:
    """Bundles the webhook route's per-request dependencies (keeps the
    route function itself under the arg-count limit)."""

    deliveries: WebhookDeliveryStore
    dismissals: DismissalStore
    ingestion: IngestionService


def _webhook_deps(
    deliveries: WebhookDeliveryStore = Depends(get_webhook_delivery_store),
    dismissals: DismissalStore = Depends(get_dismissal_store),
    ingestion: IngestionService = Depends(get_ingestion_service),
) -> _WebhookDeps:
    return _WebhookDeps(deliveries, dismissals, ingestion)


@router.post("/webhook", dependencies=[Depends(verify_signature)])
async def github_webhook(
    request: Request,
    settings: Settings = Depends(get_settings),
    deps: _WebhookDeps = Depends(_webhook_deps),
) -> JSONResponse:
    """
    Accept a GitHub webhook and, if qualifying, start a run.

    Order: signature (dependency) → parse → event/action/label/repo gating
    → dismissal → dedup → dispatch. Authentic-but-non-triggering deliveries
    are acknowledged with 200 so GitHub stops retrying (FR-011); a
    qualifying delivery returns 202 with the work dispatched in the
    background (FR-005).
    """
    event = request.headers.get("X-GitHub-Event", "")
    delivery = request.headers.get("X-GitHub-Delivery", "")
    if not event or not delivery:
        raise HTTPException(status_code=400, detail="missing webhook headers")
    payload = await _payload_from(request)

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
        if (
            action != "labeled"
            or not is_trigger
            or not watched
            or not isinstance(repo, str)
        ):
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
