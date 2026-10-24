"""Which ticket comments are replies, which decision they answer, and who
may give it (feature 046, research R8 and R9).

Pure rules, no I/O, so the security-relevant part of reading replies is
small and tested on its own:

- **A reply** carries the plain-text reply marker (``@kestrel`` by
  default) as a whole word, in any case. kestrel's own comments are
  skipped by their ``Marker("posted")``: kestrel posts through the same
  Jira account as the operator, and its announcements tell people to
  reply with the marker, so they contain it too. The operator's own
  unmarked replies are treated like anyone's.
- **The decision** a reply answers is the gate that was open when it was
  written, so a reply to a gate decided meanwhile (in the UI, or by an
  earlier reply) is told so, and never decides the next gate.
- **Old replies do not count**: a reply may only act on a gate if it was
  written after kestrel's announcement of that gate was posted (the
  ledger's completion time; clock skew with the ticket is accepted). Such
  a comment is ignored without an answer.
- **Who may decide**: the reporter decides the requester's gates, the
  change owner the two CAB gates, both by account id. An empty account id
  (a Jira Server user without one) never matches anyone.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from app.models_board import CardKind, CardState, WorkCard
from app.models_board_records import BoardEventRecord, HumanGateRecord
from app.ports import Feedback, Person, Task
from app.services.task_source_utils import POSTED

REPORTER = "reporter"
CHANGE_OWNER = "change_owner"

#: Who may decide each gate kind that is put on the ticket.
_DECIDES = {
    CardKind.UNDERSTANDING_GATE.value: REPORTER,
    CardKind.STRATEGIC_INTERVIEW_GATE.value: REPORTER,
    CardKind.REFINEMENT_GATE.value: REPORTER,
    CardKind.PRD_GATE.value: REPORTER,
    CardKind.CAB1_GATE.value: CHANGE_OWNER,
    CardKind.DECOMPOSITION_GATE.value: CHANGE_OWNER,
}

#: An interview's gate asks for answers on a form, never for a decision.
INTERVIEW = "answer"

#: Each decision in words, and what the people were asked.
_DECISIONS = {
    "confirm_understanding": (
        "confirm kestrel's understanding of the request",
        "kestrel restated the request in its own words and asked whether "
        "that is right, or what needs correcting.",
    ),
    "approve_prd": (
        "sign off the PRD",
        "kestrel wrote up the product requirements and asked for them to "
        "be approved, or for what to change.",
    ),
    "approve_strategic_fit": (
        "approve the strategic fit (CAB-1)",
        "the change owner was asked to relay the change advisory board's "
        "decision on whether the request fits strategically.",
    ),
    "approve_decomposition": (
        "approve the plan and its estimates (CAB-2)",
        "the change owner was asked to relay the change advisory board's "
        "decision on the planned work and its estimates.",
    ),
}

_DECISION_EVENTS = {"gate.approved": "approved", "gate.rejected": "rejected"}


@dataclass(frozen=True)
class OpenedGate:
    """A gate put on the ticket, and when it opened."""

    card: WorkCard
    record: HumanGateRecord
    opened_at: datetime
    #: When kestrel's announcement of the gate was posted; ``None`` while
    #: it is not (``counts_for`` then refuses every reply).
    announced_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        """Whether the gate still waits for its decision."""
        return (
            self.record.decision is None
            and self.card.state == CardState.AWAITING_HUMAN.value
        )

    @property
    def is_interview(self) -> bool:
        """Whether the gate asks for interview answers."""
        return self.record.requested_decision == INTERVIEW


@dataclass(frozen=True)
class PastDecision:
    """How a gate was decided, and by whom when it was not in kestrel."""

    decision: str | None
    display_name: str = ""
    channel: str = ""


def mentions_marker(text: str, marker: str) -> bool:
    """Whether *text* carries *marker* as a whole word, in any case. An
    empty marker matches nothing."""
    if not marker.strip():
        return False
    pattern = rf"(?<!\w){re.escape(marker)}(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def is_reply(feedback: Feedback, marker: str) -> bool:
    """Whether *feedback* is a reply for kestrel: the marker, and not one
    of kestrel's own comments."""
    if POSTED in feedback.body.markers():
        return False
    return mentions_marker(feedback.body.plain_text(), marker)


def faces_ticket(card: WorkCard) -> bool:
    """Whether *card* is a gate put on the ticket."""
    return card.kind in _DECIDES


def decider_role(kind: str) -> str | None:
    """Who decides a *kind* gate: :data:`REPORTER`, :data:`CHANGE_OWNER`,
    or ``None`` for a gate not put on the ticket."""
    return _DECIDES.get(kind)


def entitled(kind: str, author: Person, task: Task) -> bool:
    """Whether *author* may decide a *kind* gate on *task*, by account."""
    role = decider_role(kind)
    person = {REPORTER: task.reporter, CHANGE_OWNER: task.change_owner}.get(
        role or ""
    )
    if person is None or not person.account_id or not author.account_id:
        return False
    return author.account_id == person.account_id


def gate_for(
    gates: Iterable[OpenedGate], written_at: datetime
) -> OpenedGate | None:
    """The gate a reply written at *written_at* answers.

    Of the gates opened by then, the latest still open (a decision before
    an interview, when both are); else the latest decided one, so the
    reply is told it was already decided. ``None`` when no gate had
    opened yet.
    """
    earlier = [g for g in gates if g.opened_at <= written_at]
    still_open = [g for g in earlier if g.is_open]
    if still_open:
        return max(
            still_open, key=lambda g: (not g.is_interview, g.opened_at)
        )
    return max(earlier, key=lambda g: g.opened_at, default=None)


def counts_for(gate: OpenedGate, written_at: datetime) -> bool:
    """Whether a reply written at *written_at* may act on *gate*: only if
    kestrel's announcement of it was posted first. A comment from before
    (or while the announcement is still unposted) was not written in
    answer to it and is never acted on."""
    return gate.announced_at is not None and written_at > gate.announced_at


def decision_words(gate: OpenedGate) -> tuple[str, str]:
    """The decision *gate* asks for, in words, and what was asked."""
    found = _DECISIONS.get(gate.record.requested_decision)
    if found is not None:
        return found
    title = gate.card.title
    return f'decide "{title}"', f'kestrel asked for a decision on "{title}".'


def past_decision(
    gate: OpenedGate, events: Iterable[BoardEventRecord]
) -> PastDecision:
    """How *gate* was decided, from its decision event's payload."""
    for event in events:
        decision = _DECISION_EVENTS.get(event.event_type)
        if event.card_id != gate.card.id or decision is None:
            continue
        payload = _payload(event.payload)
        return PastDecision(
            decision,
            str(payload.get("display_name") or ""),
            str(payload.get("channel") or ""),
        )
    return PastDecision(gate.record.decision)


def _payload(raw: str) -> dict:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
