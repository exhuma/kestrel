"""Shared workflow-service test doubles."""

from __future__ import annotations

from app.persistence.tables import FeedbackItemRow


class _FakeFeedbackStore:
    """In-memory feedback store double for feedback pipeline tests."""

    def __init__(self) -> None:
        self.items: dict[str, FeedbackItemRow] = {}
        self.cursors: dict[str, str] = {}

    def claim(self, item: FeedbackItemRow) -> bool:
        """Store an item unless its external identifier was already claimed."""
        if item.external_id in self.items:
            return False
        self.items[item.external_id] = item
        return True

    def queued_for(self, workflow_id: str) -> list[FeedbackItemRow]:
        """Return queued feedback items belonging to a workflow."""
        return [
            item
            for item in self.items.values()
            if item.workflow_id == workflow_id and item.state == "queued"
        ]

    def mark(self, external_id: str, state: str, target_step=None) -> None:
        """Update an item's state and optional workflow step assignment."""
        item = self.items.get(external_id)
        if item is None:
            return
        item.state = state
        if target_step is not None:
            item.target_step = target_step

    def cursor(self, scope: str) -> str | None:
        """Return the saved cursor for a polling scope, if one exists."""
        return self.cursors.get(scope)

    def set_cursor(self, scope: str, value: str) -> None:
        """Save a polling cursor for a scope."""
        self.cursors[scope] = value
