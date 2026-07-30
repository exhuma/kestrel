"""UI-mockup value object and answer-key helpers.

A leaf module (imports nothing from :mod:`app.questionnaire`) so the
questionnaire schema and the answer-validation code can both depend on it
without a cycle. The mockup *capture* logic lives separately in
``app.services.workflows.interview.mockups``.
"""
from __future__ import annotations

from pydantic import BaseModel


class Mockup(BaseModel):
    """One UI mockup screenshot shown inside the questionnaire.

    Produced by the mockup turn on a ``uiux`` round. ``name`` is the file
    under the run's ``screenshots/refine/`` folder; ``url`` is the
    screenshots route that serves its bytes; ``explanation`` is the agent's
    best-effort caption (empty when it emitted no entry for the file).
    """

    name: str
    url: str
    explanation: str = ""


#: Answer-key prefix for per-mockup feedback (``mockup:<name>``), so the
#: optional free-text feedback rides the existing answers channel without a
#: new endpoint or colliding with a question id.
MOCKUP_FEEDBACK_PREFIX = "mockup:"


def mockup_key(name: str) -> str:
    """Answer-dict key carrying the feedback for mockup ``name``."""
    return f"{MOCKUP_FEEDBACK_PREFIX}{name}"
