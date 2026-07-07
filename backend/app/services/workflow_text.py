"""Sentinel and tagged-block extraction helpers for the workflow."""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from app.models import CanonicalEvent, EventKind
from app.questionnaire import Questionnaire, parse_questionnaire_json

#: Legacy unsigned marker. Still recognised for display, but never *trusted*:
#: anyone can type it into a raw issue, so it cannot gate skipping refinement.
SENTINEL = "<!-- kestrel:refined -->"

#: Matches a trailing refined marker, optionally carrying a signed HMAC
#: (``:v1:<64 hex>``). End-anchored: a marker must sit at the end of the body
#: (modulo whitespace) to count, so it cannot be smuggled mid-text.
_SENTINEL_RE = re.compile(
    r"\s*<!-- kestrel:refined(?::v1:([0-9a-f]{64}))? -->\s*\Z"
)

#: Map a tool (its bare name, MCP prefixes stripped) to a 1-2 word verb
#: for the chip activity subtext. Unlisted tools fall back to their own
#: name, so a new tool still reads sensibly.
_TOOL_ACTIVITY = {
    "read": "reading", "grep": "reading", "glob": "reading", "ls": "reading",
    "edit": "editing", "multiedit": "editing", "write": "editing",
    "notebookedit": "editing",
    "bash": "running",
    "webfetch": "searching", "websearch": "searching",
    "task": "delegating", "todowrite": "planning",
}


def activity_for(event: CanonicalEvent) -> str | None:
    """
    Derive a 1-2 word "what is it doing now" hint from one event.

    Maps the canonical event kind (and, for a tool call, the tool name)
    to a short verb shown under a session's chip. Returns None for
    events that carry no useful activity signal (tool results, user
    text, terminal result), so the caller keeps the last hint.

    :param event: The canonical event to interpret.
    :returns: A short activity word, or None.
    """
    if event.kind == EventKind.THINKING:
        return "thinking"
    if event.kind == EventKind.ASSISTANT_TEXT:
        return "responding"
    if event.kind == EventKind.RATE_LIMIT:
        return "waiting"
    if event.kind == EventKind.TOOL_USE:
        name = (event.tool_name or "").strip().lower()
        base = name.split("__")[-1] if name else ""
        return _TOOL_ACTIVITY.get(base, base or "working")
    # A backend with no incremental text events (a plain LLM) marks the
    # start of answer generation with a SYSTEM "generating" event so the
    # chip shows life during a long local-model turn.
    if event.kind == EventKind.SYSTEM and event.subtype == "generating":
        return "responding"
    return None


def has_sentinel(body: str) -> bool:
    """Return True if the body carries a refined marker (signed or not).

    Detection only — use :func:`verify_sentinel` to decide whether the
    marker can be *trusted* to skip refinement.
    """
    return _SENTINEL_RE.search(body) is not None


def _strip_sentinel(body: str) -> str:
    """Return ``body`` with any trailing refined marker removed, rstripped."""
    return _SENTINEL_RE.sub("", body).rstrip()


def _sentinel_mac(base: str, secret: str) -> str:
    """HMAC-SHA256 of the marker-free body under ``secret``."""
    return hmac.new(
        secret.encode(), base.encode(), hashlib.sha256
    ).hexdigest()


def append_sentinel(body: str, secret: str | None = None) -> str:
    """Append the refined marker to a body, at most once.

    When ``secret`` is set the marker carries an HMAC over the marker-free
    body, so :func:`verify_sentinel` can later confirm kestrel authored the
    refined text. Without a secret it degrades to the legacy unsigned marker
    that ``verify_sentinel`` never trusts.

    :param body: The refined issue body to mark.
    :param secret: The signing secret, or None/empty for an unsigned marker.
    :returns: The body with exactly one trailing marker.
    """
    base = _strip_sentinel(body)
    if secret:
        mac = _sentinel_mac(base, secret)
        return f"{base}\n\n<!-- kestrel:refined:v1:{mac} -->\n"
    return f"{base}\n\n{SENTINEL}\n"


def verify_sentinel(body: str, secret: str | None) -> bool:
    """Return True only if the body carries a valid *signed* marker.

    A valid signed marker proves kestrel produced the refined text, so the
    refine step may be safely skipped. An unsigned marker, a forged one, or
    body text altered after signing all fail the HMAC check and force a
    normal refinement pass. Also False when no secret is configured — never
    trust a marker by its literal string.

    :param body: The issue body to check.
    :param secret: The signing secret, or None/empty (always False).
    :returns: True only for a body whose signed marker verifies.
    """
    if not secret:
        return False
    match = _SENTINEL_RE.search(body)
    if match is None or match.group(1) is None:
        return False
    base = body[: match.start()].rstrip()
    return hmac.compare_digest(match.group(1), _sentinel_mac(base, secret))


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
