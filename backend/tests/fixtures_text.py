"""Canned agent-output-block builders, shared across the workflow test
suite. Split out of conftest.py (which re-exports these) to keep that
module under the repo's 500-line ceiling.
"""
from __future__ import annotations

import json


def _coverage(**flags: bool) -> str:
    """A completeness-critic COVERAGE block, one flag per audience."""
    audiences = [
        {"audience": a, "covered": c} for a, c in flags.items()
    ]
    return f"<COVERAGE>{json.dumps({'audiences': audiences})}</COVERAGE>"


def _coord(ids: list[str]) -> str:
    """A coordinator PROFILES block naming the profiles to interview."""
    return f"<PROFILES>{json.dumps(ids)}</PROFILES>"


def _qs(*questions: dict) -> str:
    """A generator QUESTIONS block wrapping the given questions."""
    body = json.dumps({"questions": list(questions)})
    return f"<QUESTIONS>{body}</QUESTIONS>"


def _refined(text: str) -> str:
    """A writer REFINED_ISSUE block."""
    return f"<REFINED_ISSUE>\n{text}\n</REFINED_ISSUE>"


def _verdict(
    accept: bool = True,
    feedback: str = "",
    observations: list[dict] | None = None,
) -> str:
    """A verifier VERDICT block (feature 003 autonomous loop).

    ``observations`` optionally carries self-reported http/ui findings
    (feature 005) — a list of ``{name, kind, passed, detail}`` dicts.
    """
    payload: dict = {"accept": accept, "feedback": feedback}
    if observations is not None:
        payload["observations"] = observations
    return f"<VERDICT>{json.dumps(payload)}</VERDICT>"


#: Simplest refine leg: coordinator needs nobody, writer emits the issue.
def _refine_noquestions(text: str) -> list[str]:
    return [_coord([]), _refined(text)]
