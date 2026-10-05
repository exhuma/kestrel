"""Status announcements (feature 046, R6).

"Should move on" notices mention the change owner: kestrel never changes
the status of an ingested ticket (constitution, access model, fourth
constraint), so it tells the person who can. CI and escalation lines
mention nobody.
"""
from __future__ import annotations

from app.documents import Document, Link, Text, paragraph
from app.services.board.announcements.common import (
    Context,
    addressed,
    finish,
)
from app.services.board.announcements.decisions import decision_sentence

_MOVE_ON = (
    "kestrel does not change this ticket's status, so it is yours to move "
    "on when you are ready."
)


def delivered(ctx: Context, location: str) -> Document:
    """The work is delivered: where, and that the ticket should move on."""
    where = (
        paragraph(Text("The change request: "), Link(location))
        if location.startswith(("https://", "http://"))
        else paragraph(Text(f"The work was published to {location}."))
    )
    return finish(ctx, (
        addressed(
            ctx.people.change_owner,
            "the work for this request is delivered, and the ticket "
            "should move on. " + _MOVE_ON,
        ),
        where,
    ))


def ended(ctx: Context, outcome: str, reason: str) -> Document:
    """The request failed or was cancelled: why, and that the ticket
    should move on."""
    what = (
        "kestrel could not finish this request"
        if outcome == "failed"
        else "this request was stopped before the end"
    )
    return finish(ctx, (
        addressed(
            ctx.people.change_owner,
            f"{what}, and the ticket should move on. {_MOVE_ON}",
        ),
        paragraph(Text(reason)),
    ))


def ci_failed(ctx: Context, detail: str) -> Document:
    """A required check on the change request failed."""
    return finish(ctx, (
        paragraph(Text(f"A required check on the change request failed: "
                       f"{detail}")),
    ))


def ci_repaired(ctx: Context) -> Document:
    """The required checks now pass."""
    return finish(ctx, (
        paragraph(Text("The required checks on the change request now "
                       "pass.")),
    ))


def escalation(ctx: Context, summary: str) -> Document:
    """Something needs a look from the coordinator."""
    return finish(ctx, (paragraph(Text(f"Escalation: {summary}")),))


def gate_decided(
    ctx: Context, kind: str, decision: str, title: str
) -> Document:
    """A gate was decided in kestrel: one plain sentence for its kind and
    outcome (``decisions.py``)."""
    sentence = decision_sentence(kind, decision == "approved", title)
    return finish(ctx, (paragraph(Text(sentence)),))
