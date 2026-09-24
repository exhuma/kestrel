"""Tests for the shared tagged-block extractor."""
from __future__ import annotations

from app.text_extract import extract_tag


def test_extracts_an_exact_tag_match() -> None:
    assert extract_tag("<FOO>bar</FOO>", "FOO") == "bar"


def test_trims_surrounding_whitespace() -> None:
    assert extract_tag("<FOO>\n  bar  \n</FOO>", "FOO") == "bar"


def test_returns_none_when_tag_is_absent() -> None:
    assert extract_tag("no tags here", "FOO") is None


def test_fuzzy_matches_a_typo_d_tag_name() -> None:
    assert extract_tag("<UNDERSTING>bar</UNDERSTING>", "UNDERSTANDING") == "bar"


def test_does_not_fuzzy_match_an_unrelated_tag() -> None:
    assert extract_tag("<OTHERTAG>bar</OTHERTAG>", "UNDERSTANDING") is None
