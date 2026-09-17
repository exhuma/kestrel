"""Tests for the general Marker abstraction and apply_markers helper."""

from __future__ import annotations

import pytest

from app.markers import (
    Marker,
    ReviewTokenMarker,
    SubtaskSentinel,
    apply_code_markers,
    apply_markers,
)
from app.services.workflow_text import (
    SUBTASK_SENTINEL,
    append_subtask_sentinel,
)


def test_subtask_sentinel_render_is_the_workflow_literal() -> None:
    """Ensure the marker renders exactly the workflow sentinel comment."""
    assert SubtaskSentinel().render() == SUBTASK_SENTINEL


def test_subtask_sentinel_present_in_detects_the_comment() -> None:
    """Ensure present_in is True only when the sentinel is in the body."""
    sentinel = SubtaskSentinel()
    assert not sentinel.present_in("plain body")
    assert sentinel.present_in(f"body\n\n{SUBTASK_SENTINEL}\n")


def test_subtask_sentinel_extract_is_none() -> None:
    """Ensure a content-free sentinel yields no payload on extract."""
    assert SubtaskSentinel().extract(SUBTASK_SENTINEL) is None


def test_apply_markers_appends_sentinel_once_and_idempotently() -> None:
    """Ensure apply_markers appends the sentinel and never duplicates it."""
    once = apply_markers("body", (SubtaskSentinel(),))
    assert SUBTASK_SENTINEL in once
    twice = apply_markers(once, (SubtaskSentinel(),))
    assert twice == once


def test_apply_markers_is_byte_identical_to_legacy_helper() -> None:
    """Ensure [SubtaskSentinel()] reproduces append_subtask_sentinel exactly."""
    for body in ("body", "body\n", "  padded  \n\n"):
        assert apply_markers(body, (SubtaskSentinel(),)) == (
            append_subtask_sentinel(body)
        )


def test_apply_markers_with_no_markers_is_a_noop() -> None:
    """Ensure an empty marker list leaves the body untouched."""
    assert apply_markers("body", ()) == "body"
    assert apply_markers("body") == "body"


def test_apply_code_markers_wraps_sentinel_once_and_idempotently() -> None:
    """Ensure code-marked sentinels survive repeated Cloud serialization."""
    once = apply_code_markers("body", (SubtaskSentinel(),))
    assert once.endswith(f"`{SUBTASK_SENTINEL}`\n")
    assert apply_code_markers(once, (SubtaskSentinel(),)) == once


class _SecondSentinel(Marker):
    """A second content-free marker used to exercise ordering."""

    def render(self) -> str:
        """Return this test marker's literal text."""
        return "<!-- second -->"

    def present_in(self, body: str) -> bool:
        """Return whether this marker already appears in ``body``."""
        return self.render() in body


def test_apply_markers_appends_multiple_markers_in_order() -> None:
    """Ensure several markers are appended in the order given."""
    result = apply_markers(
        "body", (SubtaskSentinel(), _SecondSentinel())
    )
    sub_pos = result.index(SUBTASK_SENTINEL)
    second_pos = result.index("<!-- second -->")
    assert sub_pos < second_pos


def test_review_token_marker_renders_bracketed_token() -> None:
    """Ensure a review token renders as [kestrel-review:<token>]."""
    assert ReviewTokenMarker("abc-1").render() == "[kestrel-review:abc-1]"


def test_review_token_marker_present_in_matches_exact_token() -> None:
    """Ensure present_in is True only for the marker's own token."""
    marker = ReviewTokenMarker("abc-1")
    assert marker.present_in("[kestrel-review:abc-1]")
    assert not marker.present_in("[kestrel-review:other]")


def test_review_token_marker_extract_returns_first_payload() -> None:
    """Ensure extract yields the first token's payload, or None."""
    assert ReviewTokenMarker("x").extract(
        "[kestrel-review:abc-1] then [kestrel-review:zzz]"
    ) == "abc-1"
    assert ReviewTokenMarker("x").extract("no token here") is None


def test_review_token_marker_is_content_bearing() -> None:
    """Ensure a review token overrides the sentinel's None extract."""
    marker = ReviewTokenMarker("tok_9")
    body = f"Revision 1: `{marker.render()}`"
    assert marker.present_in(body)
    assert marker.extract(body) == "tok_9"


def test_marker_base_is_abstract() -> None:
    """Ensure Marker cannot be instantiated without render/present_in."""

    class _Incomplete(Marker):
        pass

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]
