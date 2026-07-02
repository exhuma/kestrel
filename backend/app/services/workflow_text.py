"""Sentinel and tagged-block extraction helpers for the workflow."""
from __future__ import annotations

import re

from app.questionnaire import Questionnaire, parse_questionnaire_json

SENTINEL = "<!-- kestrel:refined -->"


def has_sentinel(body: str) -> bool:
    """Return True if the issue body was already refined."""
    return SENTINEL in body


def append_sentinel(body: str) -> str:
    """Append the sentinel to a body, at most once."""
    if has_sentinel(body):
        return body
    return f"{body.rstrip()}\n\n{SENTINEL}\n"


def _extract_tag(text: str, tag: str) -> str | None:
    """Return the trimmed content of a <tag>...</tag> block, or None."""
    match = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL
    )
    return match.group(1).strip() if match else None


def extract_refined_issue(text: str) -> str | None:
    """Return the refined issue if the agent emitted the delimiter block."""
    return _extract_tag(text, "REFINED_ISSUE")


def extract_plan(text: str) -> str | None:
    """Return the plan if the agent emitted the delimiter block."""
    return _extract_tag(text, "PLAN")


def extract_questionnaire(text: str) -> Questionnaire | None:
    """
    Return the questionnaire if the agent emitted the block.

    :param text: The agent's full response text.
    :returns: The parsed, validated questionnaire, or None if the
        tag is absent or its content is not valid JSON matching
        the schema.
    """
    raw = _extract_tag(text, "QUESTIONS")
    if raw is None:
        return None
    return parse_questionnaire_json(raw)
