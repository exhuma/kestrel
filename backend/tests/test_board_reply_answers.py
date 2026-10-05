"""How to answer, and what kestrel answers back (feature 046, User
Story 3).

``common.how_to_answer`` is the one place the "how to answer" wording
lives: decisions may now be answered on the ticket with the marker, or in
kestrel. Interviews still point only at the form. Every answer to a reply
mentions its author and never repeats the reply's words.
"""
from __future__ import annotations

import pytest

from app.documents import Document, Text, document, paragraph
from app.ports import Person
from app.services.board.announcements import gates as words
from app.services.board.announcements import replies as answers
from app.services.board.announcements.common import (
    Context,
    People,
    how_to_answer,
)
from tests.announcement_support import BASE_URL, CHANGE_OWNER, REPORTER

_AUTHOR = Person("acc-author", "Ann Author")
_BODY = document(paragraph(Text("The content.")))


def _ctx(*, base_url: str = BASE_URL, marker: str = "@kestrel",
         owner: Person | None = CHANGE_OWNER) -> Context:
    return Context("wf-1", People(REPORTER, owner), base_url, marker)


def test_how_to_answer_names_the_marker_and_kestrel() -> None:
    """Ensure people are told both ways to answer."""
    text = how_to_answer(_ctx()).content[0].value

    assert "reply on this ticket with @kestrel" in text
    assert '"@kestrel approved"' in text
    assert "answer in kestrel (link below)" in text


def test_how_to_answer_uses_the_configured_marker() -> None:
    """Ensure the wording follows ``feedback_marker``."""
    text = how_to_answer(_ctx(marker="@bot")).content[0].value

    assert "@bot" in text and "@kestrel" not in text


def test_how_to_answer_without_a_link_does_not_point_below() -> None:
    """Ensure no "link below" is promised when there is no link."""
    text = how_to_answer(_ctx(base_url="")).content[0].value

    assert "(link below)" not in text


@pytest.mark.parametrize("build", [
    lambda ctx: words.understanding(ctx, _BODY),
    lambda ctx: words.prd(ctx, _BODY),
    lambda ctx: words.cab_strategic_fit(ctx, _BODY),
    lambda ctx: words.cab_summary(ctx, _BODY),
])
def test_every_decision_says_it_can_be_answered_here(build) -> None:
    """Ensure the requester's and the CAB decisions all invite a reply."""
    assert "reply on this ticket with @kestrel" in build(_ctx()).plain_text()


def test_a_cab_decision_still_says_the_status_is_not_changed() -> None:
    """Ensure the change owner is still told kestrel leaves the status."""
    text = words.cab_summary(_ctx(), _BODY).plain_text()

    assert "does not change this ticket's status" in text


def test_a_cab_decision_without_a_change_owner_invites_no_reply() -> None:
    """Ensure nobody is invited to answer when nobody may."""
    text = words.cab_summary(_ctx(owner=None), _BODY).plain_text()

    assert "@kestrel" not in text


@pytest.mark.parametrize("build", [
    lambda ctx: words.strategic_interview(ctx, 2),
    lambda ctx: words.refinement_batch(
        ctx, [words.InterviewAsk("dba", 1)]
    ),
])
def test_an_interview_points_only_at_the_form(build) -> None:
    """Ensure interviews never ask for answers on the ticket."""
    text = build(_ctx()).plain_text()

    assert "@kestrel" not in text
    assert "Nothing needs to be written here" in text


_ANSWERS = [
    lambda ctx, who: answers.confirmed(ctx, who, "sign off the PRD", True),
    lambda ctx, who: answers.confirmed(ctx, who, "sign off the PRD", False),
    lambda ctx, who: answers.refused(ctx, who, "reporter"),
    lambda ctx, who: answers.refused(ctx, who, "change_owner"),
    lambda ctx, who: answers.asked_back(
        ctx, who, "sign off the PRD", reason_missing=True
    ),
    lambda ctx, who: answers.asked_back(
        ctx, who, "sign off the PRD", reason_missing=False
    ),
    answers.held,
    answers.discarded,
    lambda ctx, who: answers.already_decided(ctx, who, "approved"),
    lambda ctx, who: answers.already_decided(
        ctx, who, "rejected", ("Rita Reporter", "jira")
    ),
    answers.interview_pointer,
    answers.no_gate,
]


@pytest.mark.parametrize("build", _ANSWERS)
def test_every_answer_mentions_its_author_and_links_kestrel(build) -> None:
    """Ensure the author is notified and can reach the request."""
    answer: Document = build(_ctx(), _AUTHOR)

    assert answer.mentions() == {_AUTHOR.account_id}
    assert BASE_URL in answer.blocks[-1].content[0].href


@pytest.mark.parametrize("build", _ANSWERS)
def test_an_author_without_an_account_is_answered_without_a_mention(
    build,
) -> None:
    """Ensure an account-less author still gets a readable answer."""
    answer: Document = build(_ctx(), Person("", "Jo Server"))

    assert answer.mentions() == frozenset()
    assert answer.plain_text()[0].isupper()


def test_already_decided_says_by_whom() -> None:
    """Ensure "already decided" names who decided and where."""
    via_jira = answers.already_decided(
        _ctx(), _AUTHOR, "approved", ("Rita Reporter", "jira")
    ).plain_text()
    in_kestrel = answers.already_decided(
        _ctx(), _AUTHOR, "rejected"
    ).plain_text()

    assert "already decided (approved) by Rita Reporter via Jira" in via_jira
    assert "already decided (rejected) in kestrel" in in_kestrel
