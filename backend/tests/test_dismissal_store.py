"""Tests for the per-ticket dismissal store (task_ref key, feature 003)."""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.persistence.dismissal_store import DismissalStore
from tests.database_support import isolated_engine


def _factory() -> sessionmaker:
    """Build a sessionmaker on an isolated, migrated database."""
    return sessionmaker(bind=isolated_engine())


def test_add_then_is_dismissed() -> None:
    """Ensure a dismissed task reads back as dismissed; others do not."""
    store = DismissalStore(_factory())
    assert store.is_dismissed("o/r#7") is False
    store.add("o/r#7")
    assert store.is_dismissed("o/r#7") is True
    # A different ticket is unaffected (works for a Jira key too).
    assert store.is_dismissed("o/r#8") is False
    assert store.is_dismissed("RFC-123") is False


def test_clear_removes_dismissal() -> None:
    """Ensure clear() un-dismisses a ticket."""
    store = DismissalStore(_factory())
    store.add("RFC-123")
    store.clear("RFC-123")
    assert store.is_dismissed("RFC-123") is False


def test_add_is_idempotent() -> None:
    """Ensure adding the same dismissal twice does not error."""
    store = DismissalStore(_factory())
    store.add("o/r#7")
    store.add("o/r#7")
    assert store.is_dismissed("o/r#7") is True


def test_all_enumerates_dismissals() -> None:
    """Ensure all() lists current dismissals (poll/reconcile clear path)."""
    store = DismissalStore(_factory())
    store.add("o/r#7")
    store.add("RFC-9")
    assert set(store.all()) == {"o/r#7", "RFC-9"}
    store.clear("o/r#7")
    assert set(store.all()) == {"RFC-9"}


def test_dismissal_is_durable() -> None:
    """Ensure a dismissal survives a fresh store instance (persisted)."""
    factory = _factory()
    DismissalStore(factory).add("o/r#7")
    # A brand-new store over the same DB still sees it.
    assert DismissalStore(factory).is_dismissed("o/r#7") is True
