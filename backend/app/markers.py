"""Marker abstraction: machine-readable text attached to a task's body.

A :class:`Marker` is a piece of machine-readable text (a sentinel or a
correlation token) that the service layer decides *which* of to apply and
the task-source adapters decide *how* to emit. The adapter applies whatever
markers it is handed via :func:`apply_markers`; it never hard-codes which
markers a workflow needs. Content-free sentinels return ``None`` from
:meth:`Marker.extract`; content-bearing markers (e.g. a review token)
override it to yield their payload, so one base covers both families.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence

#: Marks a ticket as refined (feature 001).
SENTINEL = "<!-- kestrel:refined -->"
#: Marks a ticket as a technical_analysis follow-up task (feature 012): its body
#: is already self-contained and technically scoped, so a run against it
#: skips describe/refine/technical_analysis entirely and starts at design.
SUBTASK_SENTINEL = "<!-- kestrel:subtask -->"


class Marker(ABC):
    """Machine-readable text attached to a task's rendered body.

    Subclasses supply :meth:`render` (the text to emit) and
    :meth:`present_in` (idempotency / detection). The optional
    :meth:`extract` yields a content-bearing marker's payload, or ``None``
    for a content-free sentinel.
    """

    @abstractmethod
    def render(self) -> str:
        """Return the marker's text as it should appear in a body."""

    @abstractmethod
    def present_in(self, body: str) -> bool:
        """Return whether this marker already appears in ``body``."""

    def extract(self, _body: str) -> str | None:
        """Return this marker's payload from the body, or ``None``.

        The default is ``None``: a content-free sentinel carries no data to
        recover. Content-bearing markers override this and use the body.
        """
        return None


class SubtaskSentinel(Marker):
    """Marks a ticket as a technical_analysis follow-up task (feature 012).

    Its body is already self-contained and technically scoped, so a run
    against it skips describe/refine/technical_analysis and starts at design.
    Content-free: detection is by presence, not payload.
    """

    def render(self) -> str:
        """Return the subtask sentinel comment."""
        return SUBTASK_SENTINEL

    def present_in(self, body: str) -> bool:
        """Return whether the subtask sentinel already appears in ``body``."""
        return self.render() in body


class ReviewTokenMarker(Marker):
    """A content-bearing gate-review correlation token.

    Rendered as ``[kestrel-review:<token>]`` and embedded inline (inside a
    code span) by :func:`app.review_requests.render_review_request`. A body
    may carry several (one per revision), so detection is multi-occurrence
    and extraction yields the payload rather than a fixed string.
    """

    _TOKEN = re.compile(r"\[kestrel-review:([A-Za-z0-9_-]+)\]")

    def __init__(self, token: str) -> None:
        self._token = token

    @property
    def token(self) -> str:
        """The opaque correlation token this marker carries."""
        return self._token

    def render(self) -> str:
        """Return the bracketed token as it appears in a review body."""
        return f"[kestrel-review:{self._token}]"

    def present_in(self, body: str) -> bool:
        """Return whether this exact token already appears in ``body``."""
        return self.render() in body

    def extract(self, body: str) -> str | None:
        """Return the first review token in ``body``, or ``None``.

        A marker is content-bearing, so extraction returns the payload of
        the first token present (matching the legacy single-token helper).
        """
        match = self._TOKEN.search(body)
        return match.group(1) if match else None


def apply_markers(body: str, markers: Sequence[Marker] = ()) -> str:
    """Append each marker's rendered text to ``body``, at most once each.

    The single "how" every task-source adapter shares: for each marker not
    already present (per :meth:`Marker.present_in`), append its
    :meth:`Marker.render` output on its own trailing paragraph, in the
    order given. Idempotent and byte-identical to the legacy
    ``append_subtask_sentinel`` when handed ``[SubtaskSentinel()]``.

    Content-bearing markers that must appear *inline* (e.g. review tokens)
    are not applied here; they are embedded at their render site. This helper
    is for text-preserving task sources and trailing, content-free markers.
    """
    result = body
    for marker in markers:
        if not marker.present_in(result):
            result = f"{result.rstrip()}\n\n{marker.render()}\n"
    return result


def apply_code_markers(body: str, markers: Sequence[Marker] = ()) -> str:
    """Apply trailing markers, representing each as Markdown inline code.

    Jira Cloud discards an HTML comment when parsing Markdown into ADF. A code
    span produces a visible code-marked ADF text node instead, while its text
    round-trips through :func:`app.services.jira_document.to_text` unchanged.
    Existing code-wrapped markers remain unchanged, preserving idempotency.
    """
    result = apply_markers(body, markers)
    for marker in markers:
        result = _code_wrap_last_marker(result, marker.render())
    return result


def _code_wrap_last_marker(body: str, marker: str) -> str:
    """Wrap the final plain ``marker`` occurrence in a Markdown code span."""
    before, separator, after = body.rpartition(marker)
    if not separator or (before.endswith("`") and after.startswith("`")):
        return body
    return f"{before}`{marker}`{after}"
