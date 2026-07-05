"""Sentinel and tagged-block extraction helpers for the workflow."""
from __future__ import annotations

import json
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


def extract_profiles(text: str) -> list[str] | None:
    """
    Return the coordinator's chosen profile ids from a PROFILES block.

    The coordinator wraps a JSON array of profile ids (e.g.
    ``["requester", "developer"]``) — or an object with a
    ``"profiles"`` key — in ``<PROFILES>`` tags. An empty array means
    "no more rounds; the interview is done".

    :param text: The agent's full response text.
    :returns: The list of ids (possibly empty), or None if the tag is
        absent or its content is not valid JSON of the right shape.
    """
    raw = _extract_tag(text, "PROFILES")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = data.get("profiles")
    if not isinstance(data, list) or not all(
        isinstance(item, str) for item in data
    ):
        return None
    return data


def extract_coverage(text: str) -> dict[str, bool] | None:
    """
    Return the completeness critic's per-audience verdict.

    The critic wraps a JSON object in ``<COVERAGE>`` tags, either
    ``{"audiences": [{"audience": "infosec", "covered": false}, ...]}``
    or a bare ``{"infosec": false, ...}`` map. Returns a mapping of
    audience id -> covered flag, or None if the tag is absent or its
    content is not valid JSON of a recognised shape.

    :param text: The agent's full response text.
    :returns: ``{audience: covered}``, or None.
    """
    raw = _extract_tag(text, "COVERAGE")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if isinstance(data, dict) and "audiences" in data:
        data = data["audiences"]
    verdict: dict[str, bool] = {}
    if isinstance(data, list):
        for item in data:
            if (
                isinstance(item, dict)
                and isinstance(item.get("audience"), str)
                and isinstance(item.get("covered"), bool)
            ):
                verdict[item["audience"]] = item["covered"]
        return verdict or None
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(key, str) and isinstance(value, bool):
                verdict[key] = value
        return verdict or None
    return None


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
