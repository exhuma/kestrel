"""Tests for the stakeholder profile roster."""
from __future__ import annotations

from app.profiles import ROSTER, get_profile, roster_summary


def test_get_profile_returns_seeded_entry() -> None:
    """Ensure a seeded id resolves to its roster profile."""
    profile = get_profile("infosec")
    assert profile.label == "InfoSec"
    assert profile.badge == "warn"
    assert "security" in profile.system_prompt.lower()


def test_get_profile_synthesises_unknown_id() -> None:
    """Ensure an agent-minted id resolves to a generic profile."""
    profile = get_profile("observability")
    assert profile.id == "observability"
    assert profile.label == "Observability"
    assert profile.badge == "sys"
    assert profile.system_prompt  # non-empty persona


def test_roster_summary_lists_seeded_ids() -> None:
    """Ensure the coordinator summary names every seeded profile."""
    summary = roster_summary()
    for pid in ROSTER:
        assert pid in summary
