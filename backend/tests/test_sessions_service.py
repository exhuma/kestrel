"""Tests for the SessionService orchestration layer."""
from __future__ import annotations

import asyncio

import pytest

from app.models import ParsedEvent
from app.services.exceptions import SessionNotFoundError
from app.services.sessions import SessionService
from app.storage.registry import SessionRegistry


class _FakeRunner:
    """Records start/resume calls without spawning a subprocess."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def start(self, prompt: str) -> str:
        self.calls.append(("start", prompt))
        return "new-1"

    async def resume(self, session_id: str, prompt: str) -> str:
        self.calls.append(("resume", session_id, prompt))
        return session_id

    def terminate(self, session_id: str) -> bool:
        self.calls.append(("terminate", session_id))
        return True


def _service() -> tuple[SessionService, SessionRegistry, _FakeRunner]:
    registry = SessionRegistry()
    runner = _FakeRunner()
    return SessionService(runner, registry), registry, runner  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_start_delegates_to_runner() -> None:
    """Ensure start forwards the prompt to the runner."""
    service, _, runner = _service()
    sid = await service.start("hello")
    assert sid == "new-1"
    assert runner.calls == [("start", "hello")]


@pytest.mark.asyncio
async def test_resume_unknown_raises_not_found() -> None:
    """Ensure resuming an unknown session raises the domain error."""
    service, _, _ = _service()
    with pytest.raises(SessionNotFoundError):
        await service.resume("missing", "again")


@pytest.mark.asyncio
async def test_resume_resets_status_to_running() -> None:
    """Ensure resume flips an idle session back to running."""
    service, registry, runner = _service()
    registry.create("s1", "/tmp/s1")
    registry.set_status("s1", "idle")
    sid = await service.resume("s1", "again")
    assert sid == "s1"
    assert registry.get("s1").status == "running"
    assert runner.calls == [("resume", "s1", "again")]


def test_delete_unknown_raises_not_found() -> None:
    """Ensure abandoning an unknown session raises the domain error."""
    service, _, _ = _service()
    with pytest.raises(SessionNotFoundError):
        service.delete("missing")


def test_delete_terminates_subprocess_and_removes_record() -> None:
    """Ensure abandon kills the subprocess and drops the record."""
    service, registry, runner = _service()
    registry.create("s1", "/tmp/s1")
    service.delete("s1")
    assert registry.get("s1") is None
    assert ("terminate", "s1") in runner.calls


def test_list_summaries_shape() -> None:
    """Ensure summaries expose id, status and event count."""
    service, registry, _ = _service()
    registry.create("s1", "/tmp/s1")
    registry.append_event("s1", ParsedEvent("assistant", "s1", {}))
    summaries = service.list_summaries()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.session_id == "s1"
    assert summary.status == "running"
    assert summary.event_count == 1


@pytest.mark.asyncio
async def test_stream_replays_then_streams_live_and_unsubscribes() -> None:
    """Ensure stream replays stored events, yields live ones, cleans up."""
    service, registry, _ = _service()
    registry.create("s1", "/tmp/s1")
    registry.append_event("s1", ParsedEvent("system", "s1", {"n": 1}))
    registry.append_event("s1", ParsedEvent("assistant", "s1", {"n": 2}))

    gen = service.stream("s1")
    first = await gen.__anext__()
    second = await gen.__anext__()
    assert first == {"type": "system", "session_id": "s1", "raw": {"n": 1}}
    assert second["raw"] == {"n": 2}

    # The live event must be appended only after the generator has
    # subscribed (which happens once replay is exhausted), mirroring a
    # real client that connects before new events arrive.
    task = asyncio.create_task(gen.__anext__())
    while not registry._subs.get("s1"):
        await asyncio.sleep(0)
    registry.append_event("s1", ParsedEvent("result", "s1", {"n": 3}))
    third = await asyncio.wait_for(task, timeout=1.0)
    assert third["type"] == "result"

    await gen.aclose()
    assert registry._subs.get("s1") == []


@pytest.mark.asyncio
async def test_stream_unknown_session_yields_nothing_no_leak() -> None:
    """Ensure streaming an unknown session leaves no subscriber queue."""
    service, registry, _ = _service()
    gen = service.stream("missing")
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert not registry._subs.get("missing")
