"""External gate-review rendering and deterministic response classification."""

from __future__ import annotations

import re

from app.services.feedback.marker import (
    GateFeedbackAction,
    gate_feedback_action,
)

ReviewDecision = GateFeedbackAction | None
_TOKEN_PATTERN = re.compile(r"\[kestrel-review:([A-Za-z0-9_-]+)\]")
_REQUEST_PATTERN = re.compile(
    r"Revision \d+: `\[kestrel-review:[A-Za-z0-9_-]+\]`\n\n"
    r"(?:Reply to this review with its token|Reply with one command:)",
)
_APPROVAL = re.compile(r"\b(?:approve|approved|looks? good|ship it)\b", re.I)
_REJECTION = re.compile(r"\b(?:reject|rejected|do not proceed)\b", re.I)
_CHANGES = re.compile(
    r"\b(?:request(?:ed)? changes?|needs? changes?|revise|update|change)\b",
    re.I,
)


def review_tokens(body: str) -> list[str]:
    """Return every review revision token in ``body``, in body order."""
    return _TOKEN_PATTERN.findall(body)


def review_token(body: str) -> str | None:
    """Extract the first review revision token from ``body``, if present."""
    match = _TOKEN_PATTERN.search(body)
    return match.group(1) if match else None


def is_kestrel_review_request(body: str) -> bool:
    """Return whether ``body`` is Kestrel's own review-request template.

    The complete request framing is required, leaving legitimate replies with
    tokens eligible for gate processing.
    """
    return _REQUEST_PATTERN.search(body) is not None


def classify_review_response(body: str, marker: str) -> ReviewDecision:
    """Classify explicit commands or unambiguous ordinary-language decisions."""
    explicit = gate_feedback_action(body, marker)
    if re.search(re.escape(marker) + r"\s+", body, re.I):
        return explicit
    if _REJECTION.search(body):
        return "reject"
    if _CHANGES.search(body):
        return "request_changes"
    if _APPROVAL.search(body):
        return "approve"
    return None
