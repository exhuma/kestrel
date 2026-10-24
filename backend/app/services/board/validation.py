"""Closed verifier-finding schema and routing classification (feature 026,
T050, FR-027/FR-028).

Unlike ``coordinator.py``'s lenient action parsing (an unrecognized action
type is dropped, letting the rest of a batch still apply), an unrecognized
finding category is rejected outright: a finding is either safely
internal (remediation) or must reach the coordinator (escalation), and
silently defaulting an unknown category either way would be wrong for
some case. The verifier's own dispatch and card-lifecycle wiring
(remediation/escalation card creation) is a later phase's concern — this
module only defines the trustworthy shape and its routing classification.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.text_extract import extract_tag

#: FR-027: implementation nonconformance or verification gaps stay internal.
_REMEDIATION_CATEGORIES = frozenset({"nonconformance", "verification_gap"})

#: FR-028: ambiguity, requirement conflict, infeasibility, and material
#: security/policy risk must reach the coordinator as a structured
#: escalation; the verifier never resolves these itself.
_ESCALATION_CATEGORIES = frozenset(
    {"ambiguity", "requirement_conflict", "infeasibility", "policy_risk"}
)

VALID_FINDING_CATEGORIES = _REMEDIATION_CATEGORIES | _ESCALATION_CATEGORIES


class VerifierResultError(Exception):
    """Raised when a verifier's result cannot be trusted."""


@dataclass(frozen=True)
class VerifierFinding:
    """One closed-vocabulary verifier finding (data-model.md-adjacent;
    FR-027/FR-028 define its two possible routes).

    :param category: One of :data:`VALID_FINDING_CATEGORIES`.
    :param summary: Safe, operator-facing description.
    :param card_id: The card this finding concerns, if any.
    """

    category: str
    summary: str
    card_id: str | None = None


def parse_verifier_result(text: str) -> list[VerifierFinding]:
    """Parse the verifier's ``<VERIFIER_FINDINGS>`` block.

    :raises VerifierResultError: If the tag is absent, the block isn't
        valid JSON of the right shape, or any entry has an unrecognized
        category — always fail closed rather than guess a route.
    """
    raw = extract_tag(text, "VERIFIER_FINDINGS")
    if raw is None:
        raise VerifierResultError("no VERIFIER_FINDINGS block")
    try:
        data = json.loads(raw)
        entries = data["findings"]
        if not isinstance(entries, list):
            raise VerifierResultError("findings must be a list")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise VerifierResultError(f"malformed result: {exc}") from exc
    return [_parse_one(entry) for entry in entries]


def _parse_one(entry: object) -> VerifierFinding:
    if not isinstance(entry, dict):
        raise VerifierResultError(f"malformed finding entry: {entry!r}")
    try:
        finding = VerifierFinding(
            category=entry["category"],
            summary=entry["summary"],
            card_id=entry.get("card_id"),
        )
    except (KeyError, TypeError) as exc:
        raise VerifierResultError(
            f"malformed finding entry: {entry!r}"
        ) from exc
    if finding.category not in VALID_FINDING_CATEGORIES:
        raise VerifierResultError(
            f"unrecognized finding category: {finding.category!r}"
        )
    return finding


def is_remediation(finding: VerifierFinding) -> bool:
    """Whether *finding* stays entirely inside the internal code/verify
    loop (FR-027)."""
    return finding.category in _REMEDIATION_CATEGORIES


def is_escalation(finding: VerifierFinding) -> bool:
    """Whether *finding* must reach the coordinator as a structured
    escalation (FR-028)."""
    return finding.category in _ESCALATION_CATEGORIES
