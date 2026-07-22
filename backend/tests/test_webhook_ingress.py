"""Tests for the GitHub webhook ingress endpoint."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.config import Settings, get_settings
from app.main import create_app
from app.persistence.dismissal_store import get_dismissal_store
from app.persistence.webhook_delivery_store import (
    get_webhook_delivery_store,
)
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


def _client(deliveries, dismissals, ingestion):
    app = create_app()
    settings = Settings(
        _env_file=None,
        webhook_secret=_SECRET,
        watched_repos=["o/r"],
        trigger_label="kestrel",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_webhook_delivery_store] = lambda: deliveries
    app.dependency_overrides[get_dismissal_store] = lambda: dismissals
    app.dependency_overrides[get_ingestion_service] = lambda: ingestion
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
