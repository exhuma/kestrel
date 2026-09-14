"""Focused tests for mandatory verifier boundary evidence."""
from __future__ import annotations

from typing import Literal

from app.ports import Evidence, Observation
from app.services.workflows.verify import _boundary_evidence_feedback


def _observation(kind: Literal["http", "ui"]) -> Observation:
    """Build one passing observation for a supported boundary kind."""
    return Observation(name=f"{kind} probe", kind=kind, passed=True)


def test_declared_boundaries_require_matching_evidence() -> None:
    """Each declared boundary accepts only when its matching kind is present."""
    assert _boundary_evidence_feedback(Evidence(), "http")
    assert _boundary_evidence_feedback(Evidence(), "ui")
    assert _boundary_evidence_feedback(Evidence([_observation("http")]), "both")
    assert not _boundary_evidence_feedback(
        Evidence([_observation("http"), _observation("ui")]), "both"
    )


def test_malformed_verdict_observations_are_missing_evidence() -> None:
    """Dropped malformed observations cause the same actionable rejection."""
    feedback = _boundary_evidence_feedback(Evidence(), "ui")
    assert "Missing required ui boundary evidence" in feedback
    assert "well-formed observation" in feedback
