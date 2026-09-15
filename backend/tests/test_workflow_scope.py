"""Tests for fail-closed PRD scope decisions."""

from __future__ import annotations

from app.services.workflows.scope import _parse_decision, refusal_message


def test_scope_parser_rejects_malformed_response() -> None:
    """Ensure an unstructured scope response cannot authorize a change."""
    decision = _parse_decision("I think that seems reasonable.")

    assert decision.allowed is False
    assert "could not validate" in decision.reason


def test_refusal_message_explains_the_prd_boundary() -> None:
    """Ensure requester-facing refusals state the required remediation."""
    decision = _parse_decision(
        '<SCOPE>{"allowed": false, "reason": "Adds an outcome."}</SCOPE>'
    )

    message = refusal_message(decision)
    assert "Adds an outcome." in message
    assert "accepted PRD" in message
    assert "Revise and approve the PRD" in message
