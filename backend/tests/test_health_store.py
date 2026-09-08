"""Tests for HealthStore (feature 014)."""
from __future__ import annotations

from app.services.health import HealthState, HealthStore


def test_new_entries_start_unknown() -> None:
    """Ensure every registered name starts unknown, never a false
    healthy (FR-009)."""
    store = HealthStore(["github", "jira"])
    entries = {e.name: e for e in store.list_all()}
    assert entries["github"].state == HealthState.UNKNOWN
    assert entries["github"].checked_at is None
    assert entries["jira"].state == HealthState.UNKNOWN


def test_set_updates_state_and_checked_at() -> None:
    """Ensure set() records the outcome and stamps checked_at."""
    store = HealthStore(["github"])
    store.set("github", healthy=True)
    entry = store.get("github")
    assert entry is not None
    assert entry.state == HealthState.HEALTHY
    assert entry.checked_at is not None


def test_set_unhealthy() -> None:
    """Ensure a failed check is recorded as unhealthy."""
    store = HealthStore(["jira"])
    store.set("jira", healthy=False)
    assert store.get("jira").state == HealthState.UNHEALTHY


def test_set_on_unregistered_name_is_a_noop() -> None:
    """Ensure setting an unknown name doesn't raise or create an entry."""
    store = HealthStore(["github"])
    store.set("does-not-exist", healthy=True)
    assert store.get("does-not-exist") is None
    assert [e.name for e in store.list_all()] == ["github"]


def test_list_all_preserves_registration_order() -> None:
    """Ensure list_all() is stable, not sorted (data-model.md)."""
    store = HealthStore(["jira", "gitlab", "github"])
    assert [e.name for e in store.list_all()] == ["jira", "gitlab", "github"]
