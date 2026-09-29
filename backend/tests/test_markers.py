"""Tests for the general Marker abstraction and apply_markers helper."""

from __future__ import annotations

import pytest

from app.markers import (
    Marker,
    ReviewTokenMarker,
    apply_code_markers,
    apply_markers,
)

_FIRST = "<!-- first -->"


class _Sentinel(Marker):
    """A content-free marker for exercising the generic helpers."""

    def __init__(self, text: str = _FIRST) -> None:
        self._text = text

    def render(self) -> str:
        """Return this test marker's literal text."""
        return self._text

    def present_in(self, body: str) -> bool:
        """Return whether this marker already appears in ``body``."""
        return self.render() in body


def test_a_content_free_marker_extracts_nothing() -> None:
    """Ensure a sentinel-style marker yields no payload on extract."""
    assert _Sentinel().extract(_FIRST) is None


def test_apply_markers_appends_sentinel_once_and_idempotently() -> None:
    """Ensure apply_markers appends the sentinel and never duplicates it."""
    once = apply_markers("body", (_Sentinel(),))
    assert once == f"body\n\n{_FIRST}\n"
    twice = apply_markers(once, (_Sentinel(),))
    assert twice == once


def test_apply_markers_with_no_markers_is_a_noop() -> None:
    """Ensure an empty marker list leaves the body untouched."""
    assert apply_markers("body", ()) == "body"
    assert apply_markers("body") == "body"


def test_apply_code_markers_wraps_sentinel_once_and_idempotently() -> None:
    """Ensure code-marked sentinels survive repeated Cloud serialization."""
    once = apply_code_markers("body", (_Sentinel(),))
    assert once.endswith(f"`{_FIRST}`\n")
    assert apply_code_markers(once, (_Sentinel(),)) == once


def test_apply_markers_appends_multiple_markers_in_order() -> None:
    """Ensure several markers are appended in the order given."""
    result = apply_markers(
        "body", (_Sentinel(), _Sentinel("<!-- second -->"))
    )
    first_pos = result.index(_FIRST)
    second_pos = result.index("<!-- second -->")
    assert first_pos < second_pos


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
