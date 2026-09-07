"""Tests for the stakeholder profile roster."""
from __future__ import annotations

import pytest

from app.profiles import (
    BUSINESS_ALTITUDE_IDS,
    ROSTER,
    TECHNICAL_ALTITUDE_IDS,
    get_profile,
    roster_summary,
)

#: Specialists added in the roster-expansion round, with the label and
#: badge tone each is expected to resolve to.
_ADDED_PROFILES = {
    "uiux": ("UX", "ok"),
    "dba": ("DBA", "sys"),
    "pm": ("PM", "user"),
    "qa": ("QA", "err"),
    "architect": ("Arch", "agent"),
    "ops": ("Ops", "warn"),
}


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


@pytest.mark.parametrize("pid,expected", _ADDED_PROFILES.items())
def test_added_profiles_resolve(pid: str, expected: tuple[str, str]) -> None:
    """Ensure each added specialist resolves with its label and badge."""
    label, badge = expected
    profile = get_profile(pid)
    assert profile.label == label
    assert profile.badge == badge
    assert profile.system_prompt  # non-empty persona


def test_roster_summary_lists_seeded_ids() -> None:
    """Ensure the coordinator summary names every seeded profile."""
    summary = roster_summary()
    for pid in ROSTER:
        assert pid in summary


def test_business_altitude_ids_are_non_technical_only() -> None:
    """Ensure the business-altitude roster excludes every technical
    profile (feature 012, spec.md FR-004)."""
    assert {"requester", "pm", "uiux"} == BUSINESS_ALTITUDE_IDS
    assert BUSINESS_ALTITUDE_IDS.isdisjoint(TECHNICAL_ALTITUDE_IDS)


def test_technical_altitude_ids_cover_the_technical_specialists() -> None:
    """Ensure the technical-altitude roster matches research.md R7's list
    and excludes every business-altitude profile."""
    assert {
        "developer", "infosec", "dba", "architect", "ops", "qa",
    } == TECHNICAL_ALTITUDE_IDS
    assert TECHNICAL_ALTITUDE_IDS.isdisjoint(BUSINESS_ALTITUDE_IDS)


def test_roster_summary_restricts_to_given_ids() -> None:
    """Ensure passing ids to roster_summary renders only those profiles."""
    summary = roster_summary(BUSINESS_ALTITUDE_IDS)
    listed = {
        line.split(":", 1)[0].strip("- ") for line in summary.splitlines()
    }
    assert listed == BUSINESS_ALTITUDE_IDS


def test_roster_summary_with_no_ids_lists_everyone() -> None:
    """Ensure the default (no restriction) behaviour is unchanged."""
    summary = roster_summary()
    for pid in ROSTER:
        assert pid in summary


def test_added_profiles_carry_a_when_to_summon_signal() -> None:
    """Ensure each added specialist's roster line tells a selective
    coordinator when to summon it (the signal it leans on)."""
    lines = {
        line.split(":", 1)[0].strip("- "): line
        for line in roster_summary().splitlines()
    }
    for pid in _ADDED_PROFILES:
        assert pid in lines
        assert "Summon" in lines[pid]
