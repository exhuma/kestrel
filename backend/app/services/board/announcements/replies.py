"""What kestrel answers to a reply on the ticket (feature 046, User
Story 3).

Every considered reply gets one short answer, mentioning its author: the
decision was recorded, the author may not decide this, kestrel needs the
reply said again, the reply is held for review, the decision was already
taken, interview answers belong on the form, or nothing is waiting. None
repeats the reply's own words.
"""
from __future__ import annotations

from app.documents import Document
from app.ports import Person
from app.services.board.announcements.common import (
    Context,
    addressed,
    finish,
)
from app.services.board.gate_decision import channel_name

_NOTHING_CHANGED = "Nothing was changed."
_WHO = {
    "reporter": "the person who reported this ticket",
    "change_owner": "the change owner set on this ticket",
}


def confirmed(
    ctx: Context, author: Person, decision: str, approved: bool
) -> Document:
    """The reply decided: what was recorded."""
    verb = "approved" if approved else "rejected"
    return finish(ctx, (
        addressed(
            author,
            f'thank you, kestrel has recorded that you {verb} "{decision}".',
        ),
    ))


def refused(ctx: Context, author: Person, role: str | None) -> Document:
    """The author may not decide the open gate."""
    who = _WHO.get(role or "", "someone else")
    return finish(ctx, (
        addressed(
            author,
            f"only {who} can decide this here. {_NOTHING_CHANGED}",
        ),
    ))


def asked_back(
    ctx: Context, author: Person, decision: str, *, reason_missing: bool
) -> Document:
    """kestrel could not act on the reply: say what it needs."""
    if reason_missing:
        text = (
            f"kestrel needs to know why before it can record a no to "
            f'"{decision}": please reply again with '
            f"{ctx.marker} and what needs changing."
        )
    else:
        text = (
            f'kestrel could not tell whether you approve "{decision}". '
            f"Please reply again with {ctx.marker} and a clear yes, or "
            "no and why."
        )
    return finish(ctx, (
        addressed(author, f"{text} {_NOTHING_CHANGED}"),
    ))


def held(ctx: Context, author: Person) -> Document:
    """Screening held the reply back for the operator."""
    return finish(ctx, (
        addressed(
            author,
            "your reply is held for a security review, and kestrel will "
            "not act on it until it is cleared.",
        ),
    ))


def discarded(ctx: Context, author: Person) -> Document:
    """The operator discarded a held reply."""
    return finish(ctx, (
        addressed(
            author,
            "your reply was held for a security review and has not been "
            f"acted on. {_NOTHING_CHANGED}",
        ),
    ))


def already_decided(
    ctx: Context,
    author: Person,
    decision: str | None,
    by: tuple[str, str] = ("", ""),
) -> Document:
    """The gate was decided before this reply was read; *by* is who
    decided and through which channel, empty for kestrel's UI."""
    name, channel = by
    how = f" ({decision})" if decision else ""
    if channel:
        who = f" by {name or 'someone'} via {channel_name(channel)}"
    else:
        who = " in kestrel"
    return finish(ctx, (
        addressed(
            author,
            f"this was already decided{how}{who}. {_NOTHING_CHANGED}",
        ),
    ))


def interview_pointer(ctx: Context, author: Person) -> Document:
    """Interview answers are given on the form, not on the ticket."""
    where = "(link below)" if ctx.page(interview=True) else "in kestrel"
    return finish(ctx, (
        addressed(
            author,
            "interview answers are given on the short form in kestrel "
            f"{where}, not here. {_NOTHING_CHANGED}",
        ),
    ), interview=True)


def no_gate(ctx: Context, author: Person) -> Document:
    """Nothing on this request waits for a decision."""
    return finish(ctx, (
        addressed(
            author,
            "nothing on this request is waiting for a decision right now. "
            f"{_NOTHING_CHANGED}",
        ),
    ))
