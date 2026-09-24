"""Verifier-finding routing: internal remediation vs. coordinator escalation
(feature 026, T051, FR-027/FR-028).

``validation.py`` (T050) defines the trustworthy finding shape and its
routing classification; this module is the "later phase's concern" that
module's docstring deferred — turning a verifier's parsed findings into
new board cards, exclusively through ``CoordinatorService.apply_actions``
(FR-006: only the coordinator ever creates a card). This module never
touches the board store directly.

A verifier result that fails to parse is routed as an escalation too
(fail closed): an untrustworthy result must reach the coordinator, not
be silently discarded or treated as a clean pass.
"""
from __future__ import annotations

from app.models_board import CardKind, WorkCard
from app.services.board.coordinator import CoordinatorService, CreateCardAction
from app.services.board.validation import (
    VerifierFinding,
    VerifierResultError,
    is_escalation,
    parse_verifier_result,
)


def route_verifier_result(
    text: str, card: WorkCard, coordinator: CoordinatorService
) -> None:
    """Parse *card*'s verifier turn result and create any follow-up cards.

    One :class:`CreateCardAction` per finding: a remediation finding
    becomes a ``coder``-eligible ``implementation`` card, ready
    immediately (no dependency — it is new work, not a revision of the
    card it concerns); an escalation finding (or a result that fails to
    parse at all) becomes a ``coordinator_review`` card, claimed by no
    specialist. A clean result (no findings, and none of the entries
    above) creates nothing — the verification card's own acceptance
    (``artifacts.submit_result``) is the caller's separate concern.

    Idempotent per verification attempt: keyed by
    ``verification:<card.id>:<card.attempt_count>``, the same guarantee
    ``CoordinatorService.apply_actions`` already gives a repeated
    coordinator wake for one board revision.
    """
    try:
        findings = parse_verifier_result(text)
    except VerifierResultError:
        actions = [
            CreateCardAction(
                kind=CardKind.COORDINATOR_REVIEW.value,
                title=f"Unparseable verifier result on card {card.id}",
            )
        ]
    else:
        actions = [_action_for(finding) for finding in findings]
    if not actions:
        return
    trigger = f"verification:{card.id}:{card.attempt_count}"
    coordinator.apply_actions(card.workflow_id, trigger, actions)


def _action_for(finding: VerifierFinding) -> CreateCardAction:
    if is_escalation(finding):
        return CreateCardAction(
            kind=CardKind.COORDINATOR_REVIEW.value,
            title=f"Escalation: {finding.summary}",
        )
    return CreateCardAction(
        kind=CardKind.IMPLEMENTATION.value,
        title=f"Remediate: {finding.summary}",
        eligible_roles=("coder",),
        workspace_permission="write",
    )
