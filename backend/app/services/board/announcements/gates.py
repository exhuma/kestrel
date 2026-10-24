"""Announcements for a gate opening (feature 046, R6).

One builder per kind of gate. The requester's gates mention the reporter;
the two CAB gates mention the change owner and nobody else, and never a
CAB member (constitution, access model). Interview gates link to the form
and ask for nothing on the ticket.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.documents import (
    BulletList,
    Document,
    HardBreak,
    Heading,
    Inline,
    ListItem,
    Paragraph,
    Strong,
    Text,
    paragraph,
)
from app.services.board.announcements.common import (
    Context,
    addressed,
    finish,
    how_to_answer,
)

_HEADING_LEVEL = 3


@dataclass(frozen=True)
class InterviewAsk:
    """One profile's questions in an interview round."""

    persona: str
    questions: int


def understanding(ctx: Context, restatement: Document) -> Document:
    """The restatement in full, for the reporter to confirm or correct."""
    return finish(ctx, (
        addressed(
            ctx.people.reporter,
            "kestrel has put your request in its own words. Please check "
            "that it is right, or say what needs correcting.",
        ),
        *restatement.blocks,
        how_to_answer(ctx),
    ))


def strategic_interview(ctx: Context, questions: int) -> Document:
    """How many questions kestrel has, and where the form is."""
    return finish(ctx, (
        addressed(
            ctx.people.reporter,
            f"kestrel has {_questions(questions)} about how this request "
            "fits the business. They are on a short form in kestrel "
            "(link below). Nothing needs to be written here.",
        ),
    ), interview=True)


def refinement_batch(ctx: Context, asks: Sequence[InterviewAsk]) -> Document:
    """Who is asking and how much, for one round of interviews."""
    items = tuple(
        ListItem((paragraph(
            Text(f"{ask.persona}: {_questions(ask.questions)}")
        ),))
        for ask in asks
    )
    return finish(ctx, (
        addressed(
            ctx.people.reporter,
            "kestrel has more questions about this request, from the "
            "profiles below. They are on a short form in kestrel (link "
            "below). Nothing needs to be written here.",
        ),
        BulletList(items),
    ), interview=True)


def prd(ctx: Context, requirements: Document) -> Document:
    """The product requirements in full, for the reporter to approve."""
    return finish(ctx, (
        addressed(
            ctx.people.reporter,
            "kestrel has written up what it will build. Please read it and "
            "approve it, or say what to change.",
        ),
        Heading(_HEADING_LEVEL, (Text("Requirements"),)),
        *requirements.blocks,
        how_to_answer(ctx),
    ))


def cab_strategic_fit(ctx: Context, answers: Document) -> Document:
    """Ready for CAB, first look: what the requester said about
    strategic fit."""
    return finish(ctx, (
        _ready_for_cab(ctx, "the strategic fit"),
        *answers.blocks,
        _cab_decision(ctx),
    ))


def cab_summary(ctx: Context, summary: Document) -> Document:
    """Ready for CAB, second look: the executive summary of the plan."""
    return finish(ctx, (
        _ready_for_cab(ctx, "the plan and its estimates"),
        *summary.blocks,
        _cab_decision(ctx),
    ))


def answers_as_blocks(text: str) -> Document:
    """The ``Q:`` / ``A:`` text an interview answer is stored as, as
    paragraphs: each question in bold, its answer under it."""
    paragraphs: list[Paragraph] = []
    for block in text.split("\n\n"):
        inlines = _question_and_answer(block)
        if inlines:
            paragraphs.append(paragraph(*inlines))
    if not paragraphs:
        paragraphs = [paragraph(Text("No answers were recorded."))]
    return Document(tuple(paragraphs))


def _question_and_answer(block: str) -> list[Inline]:
    inlines: list[Inline] = []
    for line in filter(None, (raw.strip() for raw in block.splitlines())):
        if inlines:
            inlines.append(HardBreak())
        if line.startswith("Q:"):
            inlines.append(Strong(line[2:].strip() or "Question"))
        else:
            inlines.append(Text(line[2:].strip() if line.startswith("A:")
                                else line))
    return inlines


def _ready_for_cab(ctx: Context, what: str) -> Paragraph:
    people = ctx.people
    if people.change_owner is None and people.known:
        return paragraph(Text(
            f"This request is ready for CAB ({what}). No change owner is "
            "set on this ticket, so nobody has been asked here; the "
            "decision is taken in kestrel."
        ))
    return addressed(
        people.change_owner,
        f"this request is ready for CAB ({what}). Here is what the "
        "decision is based on.",
    )


def _cab_decision(ctx: Context) -> Paragraph:
    if ctx.people.change_owner is None and ctx.people.known:
        return paragraph(Text("Open the request in kestrel to decide."))
    answer = how_to_answer(ctx)
    return Paragraph((
        *answer.content,
        Text(" kestrel does not change this ticket's status."),
    ))


def _questions(count: int) -> str:
    return f"{count} question{'s' if count != 1 else ''}"
