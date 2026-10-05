"""The parts every announcement shares (feature 046).

Announcements are read by people who do not live in kestrel, so the
wording is plain, friendly and short. Everything a person might need to
change about *how they are asked to answer* is in :func:`how_to_answer`,
so it changes in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.documents import (
    Block,
    Document,
    Inline,
    Link,
    Mention,
    Paragraph,
    Text,
    document,
    paragraph,
)
from app.ports import Person

#: The link's wording, wherever it ends an announcement.
_LINK_TEXT = "Open this request in kestrel"


@dataclass(frozen=True)
class People:
    """The people a ticket names, as far as it could be read.

    :param known: ``False`` when the ticket could not be read, so that an
        absent change owner is not known to be absent.
    """

    reporter: Person | None = None
    change_owner: Person | None = None
    known: bool = True


@dataclass(frozen=True)
class Context:
    """What an announcement is built for: the request, who is on its
    ticket, and where kestrel can be reached (empty when not configured,
    which leaves the link out)."""

    workflow_id: str
    people: People = field(default_factory=People)
    base_url: str = ""

    def page(self, *, interview: bool = False) -> str:
        """The kestrel page for this request, or ``""`` without a base
        URL. The interview form has its own page."""
        if not self.base_url:
            return ""
        page = f"{self.base_url.rstrip('/')}/#/requests/{self.workflow_id}"
        return f"{page}/interview" if interview else page


def named(person: Person | None) -> Person | None:
    """*person* if they can be mentioned (they have an account), else
    ``None``."""
    return person if person is not None and person.account_id else None


def mention(person: Person | None) -> tuple[Inline, ...]:
    """A mention of *person* followed by a comma, or nothing at all when
    there is nobody to mention."""
    person = named(person)
    if person is None:
        return ()
    return (Mention(person.account_id, person.display_name), Text(", "))


def addressed(person: Person | None, text: str) -> Paragraph:
    """A paragraph of *text*, opening with a mention of *person* when
    there is one (and, when there is not, with a capital)."""
    opening = mention(person)
    if not opening:
        text = text[:1].upper() + text[1:]
    return paragraph(*opening, Text(text))


def how_to_answer(ctx: Context) -> Paragraph:
    """How a person answers a question put on the ticket.

    For now: on the kestrel page, which the link at the end of every
    announcement leads to.
    """
    if ctx.page():
        return paragraph(
            Text("To answer, open this request in kestrel (link below).")
        )
    return paragraph(Text("To answer, open this request in kestrel."))


def finish(
    ctx: Context, blocks: tuple[Block, ...], *, interview: bool = False
) -> Document:
    """*blocks* as one announcement, ending with the kestrel link when
    kestrel has a public address. The adapter adds the ownership marker."""
    link = ctx.page(interview=interview)
    if not link:
        return document(*blocks)
    return document(*blocks, paragraph(Link(link, _LINK_TEXT)))
