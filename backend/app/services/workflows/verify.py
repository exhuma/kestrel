"""Verdict/evidence parsing and audit-trail rendering for the verify step."""
from __future__ import annotations

import json
import logging
import re

from app.ports import Evidence, Observation

_logger = logging.getLogger(__name__)


def _render_evidence(evidence: Evidence) -> str:
    """Render a round's evidence for the committed audit-trail report
    (bounded, human-readable)."""
    if not evidence.observations:
        return "(nothing observed this round)"
    lines = []
    for obs in evidence.observations:
        mark = "PASS" if obs.passed else "FAIL"
        lines.append(f"[{mark}] ({obs.kind}) {obs.name}\n{obs.detail}".rstrip())
    return "\n\n".join(lines)


def _evidence_feedback(evidence: Evidence) -> str:
    """Summarise failing observations as actionable coder feedback."""
    fails = evidence.failures()
    if not fails:
        return ""
    parts = ["Failing observations:"]
    for obs in fails:
        parts.append(f"- {obs.name}\n{obs.detail}".rstrip())
    return "\n".join(parts)


def _render_verify_report(rounds: list[dict]) -> str:
    """Render every attempted verify round as a committed audit-trail
    artifact (feature 005, US3).

    History for a human reading the run's PR — never read back by any
    code path, so a later run's verify step cannot be influenced by it
    (FR-009).
    """
    sections = ["# Verify report", ""]
    for entry in rounds:
        sections.append(f"## Round {entry['round']}")
        sections.append(f"- Boundary: {entry['boundary'] or 'none'}")
        sections.append(
            f"- Result: {'accepted' if entry['accept'] else 'rejected'}"
        )
        if entry["feedback"]:
            sections.append(f"- Feedback: {entry['feedback']}")
        sections.append("")
        sections.append("### Evidence")
        sections.append(_render_evidence(entry["evidence"]))
        sections.append("")
    return "\n".join(sections).rstrip() + "\n"


def _clean_json_blob(blob: str) -> str:
    """Strip whitespace and a surrounding Markdown ``` fence from a blob."""
    blob = blob.strip()
    if blob.startswith("```"):
        newline = blob.find("\n")
        if newline != -1:
            blob = blob[newline + 1:]
        if blob.rstrip().endswith("```"):
            blob = blob.rstrip()[:-3]
    return blob.strip()


#: Cap on a self-reported observation's detail — keeps a verbose narrative
#: bounded and no secret an explored request could contain fully echoed
#: into a committed artifact.
_MAX_OBSERVATION_DETAIL = 2000

#: Recognised observation kinds a verdict may self-report (mirrors
#: Observation.kind); anything else is dropped rather than raising. Only
#: behavioral kinds — a technical/structural "check" observation is
#: deliberately not a legal self-report: durable checks are the coder's
#: TDD responsibility (CODE_PROMPT), not something verify re-litigates.
_OBSERVATION_KINDS = frozenset({"http", "ui"})


def _parse_observations(raw: object) -> list[Observation]:
    """Defensively build Observations from a verdict's ``observations``.

    Any entry that isn't a well-formed ``{name, kind, passed}`` object is
    dropped rather than raising — a malformed self-reported observation
    must not turn into a parse failure that rejects an otherwise-valid
    verdict.
    """
    if not isinstance(raw, list):
        return []
    observations: list[Observation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name, kind, passed = (
            item.get("name"), item.get("kind"), item.get("passed"),
        )
        if not (
            isinstance(name, str)
            and kind in _OBSERVATION_KINDS
            and isinstance(passed, bool)
        ):
            continue
        detail = item.get("detail", "")
        if not isinstance(detail, str):
            detail = ""
        observations.append(
            Observation(
                name=name, kind=kind, passed=passed,
                detail=detail[:_MAX_OBSERVATION_DETAIL],
            )
        )
    return observations


def _parse_verdict(text: str) -> tuple[bool, str, list[Observation]]:
    """Parse the verifier's verdict, tolerating common formatting.

    Reads, in order of preference: the canonical
    ``<VERDICT>{...}</VERDICT>`` block; that same JSON wrapped in a Markdown
    code fence; or, as a last resort, a bare ``{...}`` object anywhere in the
    response that carries an ``accept`` key (some models drop the tags). A
    reject-on-parse-failure is the safe default — unverified work must not
    ship autonomously — and the raw output is logged so a genuine failure is
    diagnosable rather than silent. An optional ``observations`` array
    (self-reported http/ui findings from the explore turn, feature 005) is
    parsed defensively and returned alongside the verdict; its absence is
    not a parse failure.
    """
    candidates: list[str] = []
    start = text.find("<VERDICT>")
    end = text.find("</VERDICT>")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start + len("<VERDICT>"):end])
    # Fallback for a model that omits the tags: any flat object mentioning
    # "accept". Only ever yields accept=true when the JSON explicitly says so.
    candidates.extend(
        re.findall(r"\{[^{}]*\"accept\"[^{}]*\}", text, re.DOTALL)
    )
    for blob in candidates:
        try:
            data = json.loads(_clean_json_blob(blob))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(data, dict) and "accept" in data:
            return (
                bool(data.get("accept", False)),
                str(data.get("feedback", "")),
                _parse_observations(data.get("observations")),
            )
    _logger.warning(
        "verifier produced no parseable verdict (%d chars): %r",
        len(text), text[:800],
    )
    return (
        False,
        "The verifier response could not be parsed as a verdict.",
        [],
    )
