"""The in-app notification record and its signal classification.

The old driver's message-rendering/posting notifiers (``Notifier``,
``InAppNotifier``, ``TaskSourceNotifier``, ``CompositeNotifier``) were
removed with the fixed workflow driver (Phase 10 clean break) — nothing
currently produces a ``Notification`` row. ``notification_store.py``/
``routers/notifications.py`` keep working as a generic, empty-for-now
notification center; a future board-domain producer can call
``NotificationStore.add`` directly without needing this module back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

#: A notification's signal class (see module-notification-alarm-discipline).
#: An ``action_required`` item is a gate blocking on the human; a ``summary``
#: is a terminal, catch-up item that needs no action. The UI separates them
#: so a badge count means "things needing action", not "unread everything".
SignalClass = Literal["action_required", "summary"]


def signal_class(status: str) -> SignalClass:
    """
    Classify a notification status as action-required or summary.

    :param status: The status a notification was raised for.
    :returns: ``"action_required"`` for an ``awaiting_*`` gate, else
        ``"summary"`` (terminal outcomes such as ``done``/``failed``).
    """
    return "action_required" if status.startswith("awaiting_") else "summary"


@dataclass
class Notification:
    """A recorded notification for the in-app notification center."""

    id: int
    workflow_id: str
    repo: str
    #: GitHub issue number; ``None`` for a Jira-sourced run (feature 003).
    issue_number: int | None
    status: str
    message: str
    created_at: datetime
    read: bool
