"""Structured clarification questionnaires: schema, validation,
deterministic answer formatting, and the persisted interview envelope.

Kept LLM-free by design (spec: "deterministic first") — the model
only ever produces the JSON text; every check and every rendering
decision here is plain code. In particular the "Assumptions &
accepted risks" section written into the refined issue is assembled
here from the recorded waivers, never paraphrased by the model, so an
accepted risk cannot be silently dropped.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, ValidationError

QuestionType = Literal[
    "single_select", "multi_select", "boolean", "free_text"
]

#: Default label for the per-question waiver ("I can't answer this")
#: control when the agent does not supply one.
DEFAULT_WAIVER_LABEL = "Unknown / N/A"


class QuestionOption(BaseModel):
    """One selectable option for a select-type question."""

    value: str
    label: str


class Question(BaseModel):
    """One question in a clarification questionnaire."""

    id: str
    prompt: str
    why: str = ""
    type: QuestionType
    required: bool = True
    options: list[QuestionOption] = Field(default_factory=list)
    #: Audience this question is aimed at (a profile id). Stamped by
    #: the backend from the generating profile, not self-reported.
    audience: str = ""
    #: Label for the "cannot answer — give a reason" control; the
    #: agent tailors it per question (e.g. "Accept this risk").
    waiver_label: str = DEFAULT_WAIVER_LABEL
    #: On a reconciled question, the pool question ids this one absorbed
    #: (its own basis plus any folded in). The reconciler declares these
    #: so a silent domain drop can be told apart from a real fold; empty
    #: on generator output. Provenance only — ignored by the frontend.
    folded_from: list[str] = Field(default_factory=list)


class ProfileMeta(BaseModel):
    """Lightweight profile descriptor carried to the frontend so it
    can group and badge questions without a second request."""

    id: str
    label: str
    badge: str


class Questionnaire(BaseModel):
    """A set of clarifying questions asked in one interview round."""

    questions: list[Question]
    #: Metadata for the profiles referenced by ``questions.audience``.
    profiles: list[ProfileMeta] = Field(default_factory=list)


class QAEntry(BaseModel):
    """One answered question, accumulated across interview rounds.

    Drives both the prompts handed to the agents and the deterministic
    risk section written into the refined issue.
    """

    id: str
    prompt: str
    audience: str = ""
    rendered: str = ""
    waived: bool = False
    reason: str = ""


class InterviewEnvelope(BaseModel):
    """Working state of a refine interview, persisted in the step's
    deliverable so a partial interview survives a reload/restart.

    Only ``questionnaire`` and ``draft_answers`` are consumed by the
    frontend; ``accumulated`` is backend loop state. The round counter
    is *not* carried here — it lives on the persisted step itself
    (``WorkflowStep.refine_round``), the single source of truth used to
    distinguish a genuine questionnaire change from a no-op update.
    """

    questionnaire: Questionnaire
    draft_answers: dict[str, object] = Field(default_factory=dict)
    accumulated: list[QAEntry] = Field(default_factory=list)
    #: The issue text, so the whole interview can be re-driven from the
    #: envelope alone after a restart.
    issue: str = ""


def parse_questionnaire_json(text: str) -> Questionnaire | None:
    """
    Parse bare questionnaire JSON (no surrounding tag).

    :param text: Raw JSON text, e.g. an agent's QUESTIONS block.
    :returns: The parsed questionnaire, or None if it isn't valid
        JSON matching the schema.
    """
    try:
        return Questionnaire.model_validate_json(text)
    except (ValueError, ValidationError):
        return None


def build_envelope(envelope: InterviewEnvelope) -> str:
    """Serialise an interview envelope for storage in a step."""
    return envelope.model_dump_json()


def parse_envelope(text: str) -> InterviewEnvelope | None:
    """
    Parse a stored interview envelope.

    :param text: A step deliverable written by :func:`build_envelope`.
    :returns: The envelope, or None if the text is not a valid one.
    """
    try:
        return InterviewEnvelope.model_validate_json(text)
    except (ValueError, ValidationError):
        return None


class AnswerValidationError(Exception):
    """Raised when a submitted answer set fails validation."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__(f"invalid answers: {errors}")


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == []


def is_waiver(value: object) -> bool:
    """Return True if *value* is a waiver marker (``{waived: true}``)."""
    return isinstance(value, dict) and value.get("waived") is True


def _waiver_reason(value: object) -> str:
    """Return the trimmed reason of a waiver value ("" if absent)."""
    if isinstance(value, dict):
        reason = value.get("reason")
        if isinstance(reason, str):
            return reason.strip()
    return ""


def is_custom(value: object) -> bool:
    """Return True if *value* is a custom-correction marker.

    A ``{"custom": "..."}`` answer means "none of the options fit — here
    is what the agent got wrong". Unlike a waiver it is fed back to the
    agent as a correction, never filed as an accepted risk.
    """
    return isinstance(value, dict) and isinstance(value.get("custom"), str)


def _custom_text(value: object) -> str:
    """Return the trimmed text of a custom marker ("" if absent)."""
    if isinstance(value, dict):
        text = value.get("custom")
        if isinstance(text, str):
            return text.strip()
    return ""


def _split_note(value: object) -> tuple[object, str]:
    """
    Unwrap a noted answer into its core value and its note.

    A ``{"value": <answer>, "note": "..."}`` answer carries a concrete
    answer plus optional extra detail. Any other value is its own core
    with no note.

    :returns: ``(core_value, note)``; ``note`` is "" for a plain answer.
    """
    if (
        isinstance(value, dict)
        and "value" in value
        and not is_waiver(value)
        and not is_custom(value)
    ):
        note = value.get("note")
        return value.get("value"), note.strip() if isinstance(note, str) else ""
    return value, ""


def validate_answers(
    questionnaire: Questionnaire,
    answers: dict[str, object],
    *,
    partial: bool = False,
) -> None:
    """
    Validate a submitted answer set against its questionnaire.

    A question may be answered concretely (as before), *waived* with
    ``{"waived": true, "reason": "..."}`` (always needs a non-empty
    reason), corrected with ``{"custom": "..."}`` (none of the options
    fit — needs a non-empty explanation), or annotated with
    ``{"value": <answer>, "note": "..."}`` (a concrete answer plus extra
    detail). When ``partial`` is true (a draft save) missing required
    answers are tolerated; otherwise (finalize) every required question
    must be answered, waived, or corrected.

    :param questionnaire: The questionnaire being answered.
    :param answers: Question id -> submitted value or marker.
    :param partial: Tolerate missing required answers (draft save).
    :raises AnswerValidationError: If any answer is invalid, with one
        message per offending question id.
    """
    errors: dict[str, str] = {}
    by_id = {q.id: q for q in questionnaire.questions}
    for qid in answers:
        if qid not in by_id:
            errors[qid] = "unknown question id"
    for question in questionnaire.questions:
        value = answers.get(question.id)
        if is_waiver(value):
            if not _waiver_reason(value):
                errors[question.id] = "a reason is required to waive"
            continue
        if is_custom(value):
            if not _custom_text(value):
                errors[question.id] = "an explanation is required"
            continue
        if (
            isinstance(value, dict)
            and "value" in value
            and not isinstance(value.get("note", ""), str)
        ):
            errors[question.id] = "note must be text"
            continue
        value, _ = _split_note(value)
        if _is_missing(value):
            if question.required and not partial:
                errors[question.id] = "answer required"
            continue
        if question.type == "single_select":
            valid = {o.value for o in question.options}
            if value not in valid:
                errors[question.id] = f"must be one of {sorted(valid)}"
        elif question.type == "multi_select":
            valid = {o.value for o in question.options}
            if not isinstance(value, list) or not all(
                v in valid for v in value
            ):
                errors[question.id] = (
                    f"must be a subset of {sorted(valid)}"
                )
        elif question.type == "boolean":
            if not isinstance(value, bool):
                errors[question.id] = "must be true or false"
    if errors:
        raise AnswerValidationError(errors)


def all_required_answered(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> bool:
    """
    Return True once every required question is answered or waived.

    This is the completeness gate: the interview cannot be finalized —
    and planning cannot start — until it holds.
    """
    for question in questionnaire.questions:
        if not question.required:
            continue
        value = answers.get(question.id)
        if is_waiver(value):
            if not _waiver_reason(value):
                return False
            continue
        if is_custom(value):
            if not _custom_text(value):
                return False
            continue
        value, _ = _split_note(value)
        if _is_missing(value):
            return False
    return True


def render_answer(question: Question, value: object) -> str:
    """Render one answer (waiver, correction, or note) as text."""
    if is_waiver(value):
        return f"[WAIVED: {question.waiver_label}] {_waiver_reason(value)}"
    if is_custom(value):
        return f"[NONE OF THE ABOVE — user clarification] {_custom_text(value)}"
    value, note = _split_note(value)
    rendered = _render_core(question, value)
    return f"{rendered} — additional info: {note}" if note else rendered


def _render_core(question: Question, value: object) -> str:
    """Render a concrete answer value (no marker) as text."""
    if _is_missing(value):
        return "(no answer)"
    if question.type == "boolean":
        return "Yes" if value else "No"
    if question.type == "single_select":
        labels = {o.value: o.label for o in question.options}
        return labels.get(str(value), str(value))
    if question.type == "multi_select":
        labels = {o.value: o.label for o in question.options}
        return ", ".join(
            labels.get(str(v), str(v))
            for v in value  # type: ignore[union-attr]
        )
    return str(value)


def format_answers(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> str:
    """
    Render a validated answer set as a deterministic prompt block.

    :returns: Human-readable text, one line per question.
    """
    lines = ["ANSWERS:"]
    for question in questionnaire.questions:
        rendered = render_answer(question, answers.get(question.id))
        lines.append(f"- {question.prompt}: {rendered}")
    return "\n".join(lines)


def to_entries(
    questionnaire: Questionnaire, answers: dict[str, object]
) -> list[QAEntry]:
    """
    Turn one answered round into accumulated Q&A entries.

    :returns: One entry per question, carrying its audience, rendered
        answer, and waiver reason (for the risk section).
    """
    entries: list[QAEntry] = []
    for question in questionnaire.questions:
        value = answers.get(question.id)
        entries.append(
            QAEntry(
                id=question.id,
                prompt=question.prompt,
                audience=question.audience,
                rendered=render_answer(question, value),
                waived=is_waiver(value),
                reason=_waiver_reason(value),
            )
        )
    return entries


def render_qa(entries: list[QAEntry]) -> str:
    """Render accumulated Q&A as context for the agent prompts."""
    if not entries:
        return "(no answers yet)"
    lines = ["ANSWERS SO FAR:"]
    for entry in entries:
        audience = f" [{entry.audience}]" if entry.audience else ""
        lines.append(f"- {entry.prompt}{audience}: {entry.rendered}")
    return "\n".join(lines)


def render_assumptions_and_risks(entries: list[QAEntry]) -> str:
    """
    Build the ``## Assumptions & accepted risks`` Markdown section.

    Assembled deterministically from every waived answer so a recorded
    risk acceptance survives verbatim into the refined issue. Returns
    an empty string when nothing was waived.
    """
    waived = [e for e in entries if e.waived]
    if not waived:
        return ""
    lines = ["## Assumptions & accepted risks", ""]
    for entry in waived:
        audience = f" ({entry.audience})" if entry.audience else ""
        reason = entry.reason or "(no reason given)"
        lines.append(f"- **{entry.prompt}**{audience} — {reason}")
    return "\n".join(lines) + "\n"
