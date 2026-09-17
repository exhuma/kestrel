"""External gate-review rendering and deterministic response classification."""

from __future__ import annotations

import re

from app.markers import ReviewTokenMarker
from app.services.feedback.marker import (
    GateFeedbackAction,
    gate_feedback_action,
)

ReviewDecision = GateFeedbackAction | None
#: The review-token marker's payload grammar, shared by every helper below.
_TOKEN_PATTERN = ReviewTokenMarker._TOKEN
#: A token-less instance used purely for its detection/extraction methods.
_MARKER = ReviewTokenMarker("")
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
    return _MARKER.extract(body)


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
