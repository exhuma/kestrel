"""Sentinel and tagged-block extraction helpers for the workflow."""
from __future__ import annotations

import json
import logging
import re

from app.models import CanonicalEvent, EventKind
from app.questionnaire import Questionnaire, parse_questionnaire_json

_log = logging.getLogger(__name__)

SENTINEL = "<!-- kestrel:refined -->"
#: Marks a ticket as a follow-up task published by `gap_analysis` (feature
#: 012): its body is already self-contained and technically scoped, so a
#: run against it skips describe/refine/gap_analysis entirely and starts
#: at design (see `driver.drive`).
SUBTASK_SENTINEL = "<!-- kestrel:subtask -->"

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
    """Return True if the issue body was already refined."""
    return SENTINEL in body


def append_sentinel(body: str) -> str:
    """Append the sentinel to a body, at most once."""
    if has_sentinel(body):
        return body
    return f"{body.rstrip()}\n\n{SENTINEL}\n"


def has_subtask_sentinel(body: str) -> bool:
    """Return True if the body marks a gap_analysis follow-up task."""
    return SUBTASK_SENTINEL in body


def append_subtask_sentinel(body: str) -> str:
    """Append the subtask sentinel to a body, at most once."""
    if has_subtask_sentinel(body):
        return body
    return f"{body.rstrip()}\n\n{SUBTASK_SENTINEL}\n"


def _extract_tag(text: str, tag: str) -> str | None:
    """Return the trimmed content of a <tag>...</tag> block, or None."""
    match = re.search(
        rf"<{tag}>\s*(.*?)\s*</{tag}>", text, re.DOTALL
    )
    return match.group(1).strip() if match else None


def extract_refined_issue(text: str) -> str | None:
    """Return the refined issue if the agent emitted the delimiter block."""
    return _extract_tag(text, "REFINED_ISSUE")


def extract_understanding(text: str) -> str | None:
    """Return the describe step's restatement, if the agent emitted it."""
    return _extract_tag(text, "UNDERSTANDING")


def extract_tech_analysis(text: str) -> str | None:
    """Return the gap_analysis technical-analysis summary, if emitted."""
    return _extract_tag(text, "TECH_ANALYSIS")


def _is_followup_task(item: object) -> bool:
    """Whether a parsed item is a usable follow-up task entry."""
    return (
        isinstance(item, dict)
        and isinstance(item.get("title"), str)
        and isinstance(item.get("body"), str)
    )


def extract_followup_tasks(text: str) -> list[dict[str, str]] | None:
    """
    Return the gap_analysis candidate follow-up tasks, if well-formed.

    :param text: The agent's full response text.
    :returns: A list of ``{"title", "body"}`` dicts (possibly carrying an
        extra ``"index"`` key on a revision response), or None if the
        ``<FOLLOWUP_TASKS>`` tag is absent, its JSON is malformed, or it
        contains no usable entries.
    """
    raw = _extract_tag(text, "FOLLOWUP_TASKS")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    tasks = [dict(item) for item in data if _is_followup_task(item)]
    return tasks or None


def extract_containment_verdicts(text: str) -> dict[int, dict] | None:
    """
    Return the gap_analysis self-containment critic's per-task verdicts.

    :param text: The critic's full response text.
    :returns: ``{index: {"self_contained": bool, "reason": str}}``, or
        None if the ``<CONTAINMENT>`` tag is absent or its JSON does not
        match the expected shape.
    """
    raw = _extract_tag(text, "CONTAINMENT")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, list):
        return None
    result: dict[int, dict] = {}
    for item in verdicts:
        if (
            isinstance(item, dict)
            and isinstance(item.get("index"), int)
            and isinstance(item.get("self_contained"), bool)
        ):
            result[item["index"]] = {
                "self_contained": item["self_contained"],
                "reason": item.get("reason", ""),
            }
    return result or None


def extract_plan(text: str) -> str | None:
    """Return the plan if the agent emitted the delimiter block."""
    return _extract_tag(text, "PLAN")


#: The only boundary classifications the verify step knows how to act on
#: (feature 005). Anything else — an absent tag or an out-of-vocabulary
#: value — is treated as unclassified.
_BOUNDARIES = frozenset({"http", "ui", "both", "none"})


def extract_boundary(text: str) -> str | None:
    """Return the designer's boundary classification, if well-formed.

    :param text: The designer's full response text.
    :returns: One of ``"http"``, ``"ui"``, ``"both"``, ``"none"``, or None
        when the ``<BOUNDARY>`` tag is missing or its content is not one of
        those four values.
    """
    raw = _extract_tag(text, "BOUNDARY")
    if raw is None:
        return None
    value = raw.strip().lower()
    return value if value in _BOUNDARIES else None


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


def _is_mockup(item: object) -> bool:
    """Whether a parsed item is a usable mockup entry (string ``file``)."""
    return isinstance(item, dict) and isinstance(item.get("file"), str)


def _mockup_entry(item: dict) -> dict[str, str]:
    """Normalise one mockup item to ``{"file", "explanation"}`` (strings)."""
    explanation = item.get("explanation")
    return {
        "file": item["file"],
        "explanation": explanation if isinstance(explanation, str) else "",
    }


def extract_mockups(text: str) -> list[dict[str, str]]:
    """Return the parsed ``<MOCKUPS>`` entries ``[{"file", "explanation"}]``.

    The mockup agent wraps a JSON array of ``{"file", "explanation"}``
    objects — or an object with a ``"mockups"`` key — in ``<MOCKUPS>``
    tags. Best-effort metadata: returns ``[]`` when the tag is absent or
    the JSON is missing/garbled, and keeps only entries with a string
    ``file`` (coercing a missing/non-string ``explanation`` to ``""``).

    :param text: The mockup turn's full response text.
    :returns: A list of ``{"file", "explanation"}`` dicts (possibly empty).
    """
    raw = _extract_tag(text, "MOCKUPS")
    if raw is None:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("mockups")
    if not isinstance(data, list):
        return []
    return [_mockup_entry(item) for item in data if _is_mockup(item)]


#: Legal re-entry steps a feedback-triage turn may select on *this*
#: branch's ``Step`` enum (feature 013, US3). ``describe``/``gap_analysis``
#: are feature 012 decomposition steps not present here — see
#: ``app.services.workflows.reentry.REENTRY_STEPS``, which this mirrors.
_TRIAGE_STEPS = frozenset({"refine", "design", "code"})
#: Fallback re-entry step for a parse miss or an unrecognized value
#: (never fails the dispatch outright — research.md's degrade-gracefully
#: posture).
_DEFAULT_TRIAGE_STEP = "code"
#: The empty triage result a parse miss falls back to.
_EMPTY_TRIAGE = {"step": _DEFAULT_TRIAGE_STEP, "reason": "", "instruction": ""}


def _triage_str_field(data: dict, field: str) -> str:
    value = data.get(field)
    return value if isinstance(value, str) else ""


def extract_feedback_triage(text: str) -> dict[str, str]:
    """
    Return the triage turn's classified re-entry step + instruction.

    The triage agent wraps a JSON object in ``<TRIAGE>`` tags:
    ``{"step": "code", "reason": "...", "instruction": "..."}``. A parse
    failure (missing tag, malformed JSON, not an object) falls back to
    :data:`_EMPTY_TRIAGE` wholesale; a ``step`` outside
    :data:`_TRIAGE_STEPS` falls back to ``"code"`` alone, keeping whatever
    ``reason``/``instruction`` were still well-formed. Both cases log a
    warning — this never fails the dispatch outright (FR-009).

    :param text: The triage turn's full response text.
    :returns: ``{"step", "reason", "instruction"}``, all strings.
    """
    raw = _extract_tag(text, "TRIAGE")
    if raw is None:
        _log.warning("extract_feedback_triage: no <TRIAGE> tag found")
        return dict(_EMPTY_TRIAGE)
    try:
        data = json.loads(raw)
    except ValueError:
        _log.warning("extract_feedback_triage: malformed JSON: %r", raw)
        return dict(_EMPTY_TRIAGE)
    if not isinstance(data, dict):
        _log.warning("extract_feedback_triage: not a JSON object: %r", raw)
        return dict(_EMPTY_TRIAGE)
    step = data.get("step")
    if step not in _TRIAGE_STEPS:
        _log.warning("extract_feedback_triage: unrecognized step %r", step)
        step = _DEFAULT_TRIAGE_STEP
    return {
        "step": step,
        "reason": _triage_str_field(data, "reason"),
        "instruction": _triage_str_field(data, "instruction"),
    }
