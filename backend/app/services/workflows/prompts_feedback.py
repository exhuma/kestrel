"""Prompt for the feedback-triage turn (feature 013, US3).

Kept out of ``prompts.py`` — that module is already close to the repo's
500-line module ceiling, and this feature's own ``MID_RUN_FEEDBACK_APPENDIX``
already pushed it further; a new, unrelated-in-content prompt is a clean
place to split.
"""
from __future__ import annotations

#: Triage runs once per dispatched feedback item that reaches this path
#: (terminal-run or review-origin feedback — see ``feedback/dispatch.py``'s
#: routing). It decides which step review feedback (or post-terminal
#: feedback, once US4 lands) concerns, and normalizes the raw comment into
#: a clean instruction the target step's own existing feedback-consumption
#: path (never the raw comment) actually sees.
#:
#: Only ``refine``/``design``/``code`` are offered as re-entry steps: this
#: branch's ``Step`` enum has no ``describe``/``gap_analysis`` (feature
#: 012's decomposition pipeline) — see
#: ``app.services.workflows.reentry.REENTRY_STEPS``.
FEEDBACK_TRIAGE_PROMPT = (
    "A human left feedback on this change. Decide which stage of the work "
    "it actually concerns, so it can be routed back to the right point "
    "rather than blindly re-running everything.\n"
    "Read the feedback alongside the PRD, design, and (when available) "
    "the change's diffstat below, then classify it into EXACTLY one of:\n"
    "- \"code\": the feedback is about the implementation itself (a bug, "
    "a missed detail, a code-quality concern) — the design and "
    "requirements still hold.\n"
    "- \"design\": the feedback questions the technical approach itself "
    "(architecture, data model, a different implementation strategy) — "
    "requirements still hold but the plan needs to change.\n"
    "- \"refine\": the feedback questions the requirements themselves "
    "(what should be built, not how) — the underlying PRD needs to "
    "change.\n"
    "Prefer the LATEST step that still resolves the feedback: only pick "
    "\"design\" or \"refine\" when the feedback genuinely cannot be "
    "addressed by changing code alone.\n"
    "Output ONLY a JSON object wrapped EXACTLY in <TRIAGE> and </TRIAGE> "
    "tags and nothing else, matching this shape:\n"
    '<TRIAGE>{{"step": "code", "reason": "...", "instruction": "..."}}'
    "</TRIAGE>\n"
    '"reason" is a short (one sentence) justification for the chosen '
    'step. "instruction" is a normalized restatement of the feedback — '
    "clear, actionable, and self-contained — for the target step's own "
    "prompt; it is NOT the raw feedback text verbatim. Do not edit any "
    "files.\n\nFEEDBACK:\n{feedback}\n\nPRD:\n{prd}\n\nDESIGN:\n{design}"
    "\n\n{diffstat_section}"
)

#: Interpolated into ``FEEDBACK_TRIAGE_PROMPT``'s ``{diffstat_section}``
#: slot when a diffstat is available (review-origin feedback on an open
#: PR); empty string otherwise, leaving that slot blank rather than a
#: dangling "DIFFSTAT:" heading with nothing under it.
DIFFSTAT_SECTION = "DIFFSTAT:\n{diffstat}"
