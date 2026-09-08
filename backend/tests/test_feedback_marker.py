"""Tests for the marker gate and author guard (feature 013)."""
from __future__ import annotations

import pytest

from app.services.feedback.marker import has_marker, is_ignored_author


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
