"""Who decided a gate, and what a decision must carry (feature 046,
research R12).

Two rules live here so ``gates.py`` stays within the module limit:

- a rejection the next step works from must say why: the understanding
  is redrafted from it (feature 032) and the PRD triaged from it (feature
  028). The frontend asks for the reason too, but the backend is the one
  that enforces it (constitution Principle II);
- a decision taken from a ticket records who took it, and where, in the
  ``gate.approved`` / ``gate.rejected`` event, so the request's history
  can say so. A decision without a :class:`Decider` is the operator's,
  in kestrel, as before.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

#: Decisions whose rejection must carry a non-empty answer.
REASON_REQUIRED = frozenset({"confirm_understanding", "approve_prd"})

#: How each channel is named to the operator.
_CHANNEL_NAMES = {"jira": "Jira"}

#: Who a decision is credited to when the ticket did not say.
_SOMEONE = "Someone"


class ReasonRequiredError(Exception):
    """Raised when a rejection that needs a reason comes without one."""


@dataclass(frozen=True)
class Decider:
    """Who decided a gate outside the kestrel UI.

    :param channel: Where the decision came from (``"jira"``).
    :param account_id: The decider's account on that channel.
    :param display_name: Their name, for people to read.
    :param comment_external_id: The comment that carried the decision.
    """

    channel: str
    account_id: str
    display_name: str
    comment_external_id: str = ""


def needs_reason(requested_decision: str) -> bool:
    """Whether rejecting *requested_decision* needs a reason."""
    return requested_decision in REASON_REQUIRED


def require_reason(
    requested_decision: str, decision: str, answer: str | None
) -> None:
    """Refuse a reasonless rejection where a reason is needed.

    :raises ReasonRequiredError: If *decision* rejects a gate whose
        rejection needs a reason and *answer* is empty.
    """
    if decision != "rejected" or not needs_reason(requested_decision):
        return
    if not (answer or "").strip():
        raise ReasonRequiredError(
            f"rejecting {requested_decision} needs a reason"
        )


def channel_name(channel: str) -> str:
    """*channel* as the operator reads it."""
    return _CHANNEL_NAMES.get(channel, channel)


def decision_payload(decided_by: Decider | None) -> str:
    """The decision event's payload: ``{}`` for the operator in kestrel,
    else who decided and through which channel."""
    if decided_by is None:
        return "{}"
    name = decided_by.display_name or _SOMEONE
    return json.dumps({
        "detail": f"{name} decided via {channel_name(decided_by.channel)}",
        "channel": decided_by.channel,
        "account_id": decided_by.account_id,
        "display_name": decided_by.display_name,
    })
