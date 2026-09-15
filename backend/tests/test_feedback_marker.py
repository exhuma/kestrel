"""Tests for the marker gate and author guard (feature 013)."""

from __future__ import annotations

import pytest

from app.services.feedback.marker import (
    append_comment_sentinel,
    gate_feedback_action,
    has_comment_sentinel,
    has_marker,
    is_ignored_author,
)
from app.services.feedback.review import (
    classify_review_response,
    review_token,
    review_tokens,
)


def test_comment_sentinel_marks_once_when_enabled() -> None:
    """An enabled sentinel identifies a Kestrel comment without duplication."""
    marked = append_comment_sentinel(
        "@kestrel approve", True, "[kestrel:posted]"
    )
    assert marked.endswith("\n\n[kestrel:posted]")
    assert append_comment_sentinel(
        marked, True, "[kestrel:posted]"
    ) == marked
    assert has_comment_sentinel(marked, True, "[kestrel:posted]") is True


def test_comment_sentinel_can_be_disabled() -> None:
    """The compatibility switch leaves outbound comments and intake unchanged.
    """
    body = "@kestrel approve"
    assert append_comment_sentinel(body, False, "[kestrel:posted]") == body
    assert has_comment_sentinel(
        "[kestrel:posted]", False, "[kestrel:posted]"
    ) is False


@pytest.mark.parametrize(
    "body",
    [
        "@kestrel please rename this variable",
        "thanks! @KESTREL can you look?",
        "(@Kestrel) take another pass",
        "@kestrel",
    ],
)
def test_has_marker_matches_whole_token_case_insensitively(
    body: str,
) -> None:
    """A standalone marker token matches regardless of case/punctuation."""
    assert has_marker(body, "@kestrel") is True


@pytest.mark.parametrize(
    "body",
    [
        "@kestrelbot please look",
        "notkestrel should not match",
        "just a normal comment",
        "",
    ],
)
def test_has_marker_rejects_embedded_or_missing_token(body: str) -> None:
    """A marker glued to other word characters, or absent, does not match."""
    assert has_marker(body, "@kestrel") is False


def test_has_marker_uses_the_configured_token() -> None:
    """A differently-configured marker is matched instead of the default."""
    assert has_marker("hey @bot-review take a look", "@bot-review") is True
    assert has_marker("hey @kestrel take a look", "@bot-review") is False


@pytest.mark.parametrize(
    ("body", "action"),
    [
        ("@kestrel approve", "approve"),
        ("Please @KESTREL APPROVE this revision.", "approve"),
        ("@kestrel reject", "reject"),
        ("@kestrel request changes: name the API", "request_changes"),
        ("@kestrel please rename the endpoint", "request_changes"),
    ],
)
def test_gate_feedback_action_recognizes_explicit_terms(
    body: str, action: str
) -> None:
    """Marker comments deterministically classify approval terms or changes."""
    assert gate_feedback_action(body, "@kestrel") == action


def test_is_ignored_author_denylist_match() -> None:
    """An author on the denylist is ignored, case-insensitively."""
    assert is_ignored_author("kestrel-bot", ["kestrel-bot"]) is True
    assert is_ignored_author("KESTREL-BOT", ["kestrel-bot"]) is True
    assert is_ignored_author("someone-else", ["kestrel-bot"]) is False


def test_is_ignored_author_bot_flag_overrides_denylist() -> None:
    """is_bot=True is ignored regardless of the denylist's contents."""
    assert is_ignored_author("dependabot[bot]", [], is_bot=True) is True


def test_is_ignored_author_defaults_to_not_ignored() -> None:
    """A plain human author with an empty denylist is never ignored."""
    assert is_ignored_author("octocat", []) is False


@pytest.mark.parametrize(
    ("body", "action"),
    [
        ("[kestrel-review:abc] Looks good to me.", "approve"),
        ("[kestrel-review:abc] Please revise the API name.", "request_changes"),
        ("[kestrel-review:abc] Do not proceed.", "reject"),
        ("[kestrel-review:abc] I have a question.", None),
    ],
)
def test_classify_review_response_handles_unambiguous_plain_language(
    body: str, action: str | None
) -> None:
    """Ordinary wording classifies only when it communicates a decision."""
    assert classify_review_response(body, "@kestrel") == action


def test_review_token_extracts_the_revision_token() -> None:
    """A response can quote the request token anywhere in its body."""
    assert review_token("I approve [kestrel-review:a_b-9].") == "a_b-9"


def test_review_tokens_extract_every_revision_token() -> None:
    """Quoted stale tokens do not conceal a later active token."""
    body = "[kestrel-review:stale] quoted [kestrel-review:current] approve"
    assert review_tokens(body) == ["stale", "current"]
