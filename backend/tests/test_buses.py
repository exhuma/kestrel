"""Tests for the workflow and notification SSE pub/sub buses."""
from __future__ import annotations

import pytest

from app.storage.notification_bus import NotificationBus
from app.storage.workflow_bus import WorkflowBus


@pytest.mark.asyncio
async def test_workflow_bus_fans_out_per_workflow() -> None:
    """Ensure a publish reaches only that workflow's subscribers."""
    bus = WorkflowBus()
    a = bus.subscribe("wf-1")
    b = bus.subscribe("wf-1")
    other = bus.subscribe("wf-2")

    bus.publish("wf-1")

    assert a.get_nowait() == "wf-1"
    assert b.get_nowait() == "wf-1"
    assert other.empty()


def test_workflow_bus_unsubscribe_stops_delivery() -> None:
    """Ensure an unsubscribed queue receives nothing further."""
    bus = WorkflowBus()
    q = bus.subscribe("wf-1")
    bus.unsubscribe("wf-1", q)
    bus.publish("wf-1")
    assert q.empty()


def test_workflow_bus_list_channel_ticks_on_any_change() -> None:
    """Ensure a list subscriber is ticked on any run change (live sidebar)."""
    bus = WorkflowBus()
    lst = bus.subscribe_list()
    per_run = bus.subscribe("wf-1")

    bus.publish("wf-1")  # a run changed / was created
    assert lst.get_nowait() == "wf-1"  # list channel ticked
    assert per_run.get_nowait() == "wf-1"

    bus.publish("wf-2")  # a different run — list still ticks
    assert lst.get_nowait() == "wf-2"

    bus.unsubscribe_list(lst)
    bus.publish("wf-3")
    assert lst.empty()  # unsubscribed: no further ticks


def test_notification_bus_fans_out_to_all() -> None:
    """Ensure a publish reaches every notification subscriber."""
    bus = NotificationBus()
    a = bus.subscribe()
    b = bus.subscribe()

    bus.publish()

    assert not a.empty()
    assert not b.empty()
    a.get_nowait()
    b.get_nowait()
    bus.unsubscribe(a)
    bus.publish()
    assert a.empty()  # unsubscribed: no new tick
    assert not b.empty()
