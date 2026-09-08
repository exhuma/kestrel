"""Tests for the pull_request_review/pull_request_review_comment webhook
events (feature 013, US3) — reuses test_webhook_ingress.py's fakes/client
builder rather than reinventing them."""
from __future__ import annotations

import json

import pytest

from tests.test_webhook_ingress import (
    _client,
    _FakeDeliveries,
    _FakeDismissals,
    _FakeFeedbackIntake,
    _FakeIngestion,
    _post,
    _tick,
)

_ACCEPTED = 202
_IGNORED = 200


def _review_payload(**overrides) -> bytes:
    """Build a ``pull_request_review`` payload; override via kwargs:
    ``repo``, ``pr_number``, ``review_id``, ``body``, ``author``,
    ``submitted_at``."""
    data = {
        "repo": "o/r", "pr_number": 5, "review_id": 77,
        "body": "@kestrel reconsider this", "author": "reviewer",
        "submitted_at": "2026-01-01T00:00:00Z",
    }
    data.update(overrides)
    return json.dumps({
        "action": "submitted",
        "repository": {"full_name": data["repo"]},
        "pull_request": {"number": data["pr_number"]},
        "review": {
            "id": data["review_id"], "body": data["body"],
            "user": {"login": data["author"], "type": "User"},
            "submitted_at": data["submitted_at"],
        },
    }).encode()


def _review_comment_payload(**overrides) -> bytes:
    """Build a ``pull_request_review_comment`` payload; override via
    kwargs: ``repo``, ``pr_number``, ``comment_id``, ``body``, ``author``,
    ``author_type``, ``created_at``."""
    data = {
        "repo": "o/r", "pr_number": 5, "comment_id": 88,
        "body": "@kestrel fix this line", "author": "reviewer",
        "author_type": "User", "created_at": "2026-01-01T00:00:00Z",
    }
    data.update(overrides)
    return json.dumps({
        "action": "created",
        "repository": {"full_name": data["repo"]},
        "pull_request": {"number": data["pr_number"]},
        "comment": {
            "id": data["comment_id"], "body": data["body"],
            "user": {"login": data["author"], "type": data["author_type"]},
            "created_at": data["created_at"],
        },
    }).encode()


@pytest.mark.asyncio
async def test_pull_request_review_reaches_intake_as_review_origin() -> None:
    """A review summary on a watched repo reaches intake, routed by the
    PR's own identity."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _review_payload(), event="pull_request_review",
        )
        await _tick()
    assert r.status_code == _ACCEPTED
    assert intake.calls == [
        {
            "task_ref": "o/r#5", "body": "@kestrel reconsider this",
            "author": "reviewer", "is_bot": False, "origin": "review",
        }
    ]


@pytest.mark.asyncio
async def test_pull_request_review_unwatched_repo_ignored() -> None:
    """A review on a repo with no configured github task source never
    reaches the intake pipeline."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _review_payload(repo="x/y"), event="pull_request_review",
        )
        await _tick()
    assert r.status_code == _IGNORED
    assert intake.calls == []


@pytest.mark.asyncio
async def test_pull_request_review_comment_reaches_intake() -> None:
    """An inline review comment reaches intake as review-origin feedback."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _review_comment_payload(),
            event="pull_request_review_comment",
        )
        await _tick()
    assert r.status_code == _ACCEPTED
    assert intake.calls == [
        {
            "task_ref": "o/r#5", "body": "@kestrel fix this line",
            "author": "reviewer", "is_bot": False, "origin": "review",
        }
    ]


@pytest.mark.asyncio
async def test_pull_request_review_comment_bot_author_flag_passed() -> None:
    """A Bot-typed review-comment author is flagged for intake's guard."""
    intake = _FakeFeedbackIntake()
    async with _client(
        _FakeDeliveries(), _FakeDismissals(), _FakeIngestion(), intake
    ) as c:
        r = await _post(
            c, _review_comment_payload(author_type="Bot"),
            event="pull_request_review_comment",
        )
        await _tick()
    assert r.status_code == _ACCEPTED
    assert intake.calls[0]["is_bot"] is True
