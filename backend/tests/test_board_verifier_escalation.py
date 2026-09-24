"""Ambiguity, conflict, infeasibility, and policy-risk escalation tests
(feature 026, T049, FR-028).

The verifier never modifies requirements or opens a human gate itself —
it only classifies a finding as needing coordinator escalation; a human
gate is created only if and when the coordinator's own proposed action
is policy-validated (FR-028, FR-005).
"""
from __future__ import annotations

import pytest
from app.services.board.validation import (
    VALID_FINDING_CATEGORIES,
    VerifierFinding,
    is_escalation,
    is_remediation,
)


class TestEscalationClassification:
    """Ambiguity, conflict, infeasibility, and policy risk all escalate."""

    @pytest.mark.parametrize(
        "category",
        ["ambiguity", "requirement_conflict", "infeasibility", "policy_risk"],
    )
    def test_escalation_categories_are_classified_as_escalation(
        self, category: str
    ) -> None:
        finding = VerifierFinding(category=category, summary="x")
        assert is_escalation(finding)

    @pytest.mark.parametrize(
        "category", ["nonconformance", "verification_gap"]
    )
    def test_remediation_categories_are_not_escalation(
        self, category: str
    ) -> None:
        finding = VerifierFinding(category=category, summary="x")
        assert not is_escalation(finding)


class TestClassificationIsExhaustiveAndDisjoint:
    """Every valid category is exactly one of remediation or escalation."""

    def test_every_valid_category_is_classified_one_way(self) -> None:
        for category in VALID_FINDING_CATEGORIES:
            finding = VerifierFinding(category=category, summary="x")
            assert is_remediation(finding) != is_escalation(finding)
