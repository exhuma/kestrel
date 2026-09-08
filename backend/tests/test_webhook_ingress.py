"""Tests for the GitHub webhook ingress endpoint."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.config import Settings, get_settings
from app.config_models import TaskSourceConfig
from app.main import create_app
from app.persistence.dismissal_store import get_dismissal_store
from app.persistence.webhook_delivery_store import (
    get_webhook_delivery_store,
)
from app.services.feedback import github_events
from app.services.feedback.intake import get_feedback_intake_service
from app.services.ingestion import get_ingestion_service

_SECRET = "s3cr3t"


class _FakeDeliveries:
    def __init__(self) -> None:
        self.ids: set[str] = set()

    def seen(self, delivery_id, event, outcome, repo=None, issue_number=None):
        if delivery_id in self.ids:
            return True
        self.ids.add(delivery_id)
        return False


class _FakeDismissals:
    def __init__(self) -> None:
        self._d: set[str] = set()

    def add(self, task_ref):
        self._d.add(task_ref)

    def is_dismissed(self, task_ref):
        return task_ref in self._d

    def all(self):
        return list(self._d)

    def clear(self, task_ref):
        self._d.discard(task_ref)


class _FakeIngestion:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    async def maybe_start_run(self, *, source, task_ref, code_repo,
                              issue_number=None, base_branch=None):
        self.calls.append((code_repo, issue_number))
        return "wf-x"


class _FakeFeedbackIntake:
    """Records every ``intake`` call instead of running the real pipeline
    (feature 013) — the webhook route unconditionally resolves this
    dependency, so every existing ingestion test needs a safe double too,
    not just the new feedback-specific ones."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def intake(self, feedback, *, task_ref, source, is_bot=False):
        self.calls.append(
            {
                "task_ref": task_ref,
                "body": feedback.body,
                "author": feedback.author,
                "is_bot": is_bot,
                "origin": feedback.origin,
            }
        )


def _sign(body: bytes) -> str:
    digest = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def _payload(action="labeled", repo="o/r", issue=5, label="kestrel") -> bytes:
    return json.dumps(
        {
            "action": action,
            "repository": {"full_name": repo},
            "issue": {"number": issue},
            "label": {"name": label},
        }
    ).encode()


def _comment_payload(**overrides) -> bytes:
    """Build an ``issue_comment`` webhook payload; override any field via
    kwargs: ``action``, ``repo``, ``issue``, ``body``, ``author``,
    ``author_type``, ``comment_id``, ``on_pr``."""
    data = {
        "action": "created", "repo": "o/r", "issue": 5,
        "body": "@kestrel look again", "author": "octocat",
        "author_type": "User", "comment_id": 99, "on_pr": False,
    }
    data.update(overrides)
    issue_obj: dict = {"number": data["issue"]}
    if data["on_pr"]:
        issue_obj["pull_request"] = {"url": "https://api/pulls/5"}
    return json.dumps(
        {
            "action": data["action"],
            "repository": {"full_name": data["repo"]},
            "issue": issue_obj,
            "comment": {
                "id": data["comment_id"],
                "body": data["body"],
                "user": {
                    "login": data["author"], "type": data["author_type"],
                },
                "created_at": "2026-01-01T00:00:00Z",
            },
        }
    ).encode()


def _client(deliveries, dismissals, ingestion, intake=None):
    app = create_app()
    settings = Settings(
        _env_file=None,
        webhook_secret=_SECRET,
        task_sources=[
            TaskSourceConfig(
                type="github", watched_repos=["o/r"], trigger_label="kestrel"
            )
        ],
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_webhook_delivery_store] = lambda: deliveries
    app.dependency_overrides[get_dismissal_store] = lambda: dismissals
    app.dependency_overrides[get_ingestion_service] = lambda: ingestion
    app.dependency_overrides[get_feedback_intake_service] = (
        lambda: intake if intake is not None else _FakeFeedbackIntake()
    )
    app.dependency_overrides[github_events.get_feedback_github_source] = object
    app.dependency_overrides[github_events.get_feedback_github_codehost] = (
        object
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _post(client, body, delivery="d1", event="issues", sign=None):
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "X-Hub-Signature-256": _sign(body) if sign is None else sign,
        "Content-Type": "application/json",
    }
    return await client.post(
        "/api/github/webhook", content=body, headers=headers
    )


async def _tick() -> None:
    """Let a dispatched background task run to completion."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_valid_labeled_starts_one_run() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        r = await _post(c, _payload())
        await _tick()
    assert r.status_code == 202
    assert ing.calls == [("o/r", 5)]


@pytest.mark.asyncio
async def test_invalid_signature_rejected() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        r = await _post(c, _payload(), sign="sha256=deadbeef")
        await _tick()
    assert r.status_code == 401
    assert ing.calls == []


@pytest.mark.asyncio
async def test_missing_signature_rejected() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        body = _payload()
        r = await c.post(
            "/api/github/webhook",
            content=body,
            headers={
                "X-GitHub-Event": "issues",
                "X-GitHub-Delivery": "d1",
            },
        )
    assert r.status_code == 401
    assert ing.calls == []


@pytest.mark.asyncio
async def test_duplicate_delivery_starts_one_run() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        r1 = await _post(c, _payload(), delivery="dup")
        await _tick()
        r2 = await _post(c, _payload(), delivery="dup")
        await _tick()
    assert r1.status_code == 202
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"
    assert ing.calls == [("o/r", 5)]


@pytest.mark.asyncio
async def test_non_trigger_label_ignored() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        r = await _post(c, _payload(label="other"))
        await _tick()
    assert r.status_code == 200
    assert ing.calls == []


@pytest.mark.asyncio
async def test_unwatched_repo_ignored() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        r = await _post(c, _payload(repo="x/y"))
        await _tick()
    assert r.status_code == 200
    assert ing.calls == []


@pytest.mark.asyncio
async def test_non_issues_event_ignored() -> None:
    ing = _FakeIngestion()
    async with _client(_FakeDeliveries(), _FakeDismissals(), ing) as c:
        r = await _post(c, _payload(), event="push")
        await _tick()
    assert r.status_code == 200
    assert ing.calls == []


@pytest.mark.asyncio
async def test_dismissed_issue_ignored() -> None:
    ing = _FakeIngestion()
    dis = _FakeDismissals()
    dis.add("o/r#5")
    async with _client(_FakeDeliveries(), dis, ing) as c:
        r = await _post(c, _payload())
        await _tick()
    assert r.status_code == 200
    assert ing.calls == []


@pytest.mark.asyncio
async def test_unlabeled_clears_dismissal_then_relabel_starts() -> None:
    ing = _FakeIngestion()
    dis = _FakeDismissals()
    dis.add("o/r#5")
    async with _client(_FakeDeliveries(), dis, ing) as c:
        r_unlabel = await _post(c, _payload(action="unlabeled"), delivery="d1")
        assert dis.is_dismissed("o/r#5") is False
        r_relabel = await _post(c, _payload(), delivery="d2")
        await _tick()
    assert r_unlabel.status_code == 200
    assert r_relabel.status_code == 202
    assert ing.calls == [("o/r", 5)]


# ---- issue_comment (feedback intake, feature 013) --------------------


@pytest.mark.asyncio
async def test_issue_comment_ticket_origin_reaches_intake() -> None:
    """A ticket-origin issue_comment on a watched repo is handed to
    FeedbackIntakeService with the right task_ref/body/author."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _comment_payload(), event="issue_comment", delivery="c1"
        )
        await _tick()
    assert r.status_code == 202
    assert intake.calls == [
        {
            "task_ref": "o/r#5", "body": "@kestrel look again",
            "author": "octocat", "is_bot": False, "origin": "ticket",
        }
    ]


@pytest.mark.asyncio
async def test_issue_comment_on_pull_request_reaches_intake_as_review() -> (
    None
):
    """A PR-conversation comment (issue carries pull_request) reaches
    intake as review-origin feedback (feature 013, US3), routed by the
    PR's own identity rather than the run's ticket task_ref."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _comment_payload(on_pr=True), event="issue_comment",
        )
        await _tick()
    assert r.status_code == 202
    assert intake.calls == [
        {
            "task_ref": "o/r#5", "body": "@kestrel look again",
            "author": "octocat", "is_bot": False, "origin": "review",
        }
    ]


@pytest.mark.asyncio
async def test_issue_comment_unwatched_repo_ignored() -> None:
    """A comment on a repo with no configured github task source never
    reaches the intake pipeline (avoids an open feedback-spam surface)."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _comment_payload(repo="x/y"), event="issue_comment",
        )
        await _tick()
    assert r.status_code == 200
    assert intake.calls == []


@pytest.mark.asyncio
async def test_issue_comment_non_created_action_ignored() -> None:
    """An edited/deleted comment does not re-trigger intake."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _comment_payload(action="edited"), event="issue_comment",
        )
        await _tick()
    assert r.status_code == 200
    assert intake.calls == []


@pytest.mark.asyncio
async def test_issue_comment_bot_author_flag_passed_through() -> None:
    """A GitHub Bot-typed author is flagged for intake's author guard."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _comment_payload(author_type="Bot"), event="issue_comment",
        )
        await _tick()
    assert r.status_code == 202
    assert intake.calls[0]["is_bot"] is True
