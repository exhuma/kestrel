"""Verifier finding classification and internal remediation tests
(feature 026, T048, FR-027).

Ordinary implementation defects stay entirely inside the internal code/
verify loop — the verifier resolves them without ever bothering the
operator or the coordinator's escalation path.
"""
from __future__ import annotations

import pytest
from app.services.board.validation import (
    VerifierFinding,
    VerifierResultError,
    is_remediation,
    parse_verifier_result,
)


def _findings_block(*entries: str) -> str:
    return (
        '<VERIFIER_FINDINGS>{"findings": [' + ",".join(entries) + "]}"
        "</VERIFIER_FINDINGS>"
    )


class TestParsing:
    """The verifier's structured result is parsed from its own tag."""

    def test_parses_a_well_formed_finding(self) -> None:
        text = _findings_block(
            '{"category": "nonconformance", "summary": "missing null check"}'
        )
        findings = parse_verifier_result(text)
        assert findings == [
            VerifierFinding(
                category="nonconformance", summary="missing null check"
            )
        ]

    def test_empty_findings_list_is_valid(self) -> None:
        assert parse_verifier_result(_findings_block()) == []

    def test_missing_tag_raises(self) -> None:
        with pytest.raises(VerifierResultError):
            parse_verifier_result("no structured block here")

    def test_malformed_json_raises(self) -> None:
        text = "<VERIFIER_FINDINGS>{not json}</VERIFIER_FINDINGS>"
        with pytest.raises(VerifierResultError):
            parse_verifier_result(text)

    def test_unrecognized_category_raises(self) -> None:
        """Closed vocabulary: an unknown category is rejected outright
        rather than silently defaulting to either routing path."""
        text = _findings_block(
            '{"category": "made_up_category", "summary": "x"}'
        )
        with pytest.raises(VerifierResultError):
            parse_verifier_result(text)

    def test_finding_may_reference_the_card_it_concerns(self) -> None:
        text = _findings_block(
            '{"category": "nonconformance", "summary": "x", '
            '"card_id": "card-1"}'
        )
        findings = parse_verifier_result(text)
        assert findings[0].card_id == "card-1"


class TestRemediationClassification:
    """Nonconformance and verification-gap findings stay internal."""

    @pytest.mark.parametrize(
        "category", ["nonconformance", "verification_gap"]
    )
    def test_remediation_categories_are_classified_as_remediation(
        self, category: str
    ) -> None:
        finding = VerifierFinding(category=category, summary="x")
        assert is_remediation(finding)

    @pytest.mark.parametrize(
        "category",
        ["ambiguity", "requirement_conflict", "infeasibility", "policy_risk"],
    )
    def test_escalation_categories_are_not_remediation(
        self, category: str
    ) -> None:
        finding = VerifierFinding(category=category, summary="x")
        assert not is_remediation(finding)
